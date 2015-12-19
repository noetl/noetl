package com.noetl.automation.services;

import com.noetl.aws.EMRClusterClient;
import com.noetl.parsers.JsonParser;
import com.noetl.pojos.AutomationConf;
import com.noetl.pojos.clusterConfigs.ClusterConfJson;
import com.noetl.utils.GeneralUtils;
import org.apache.log4j.Logger;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

public class ClusterTerminationService extends BaseService {

  private static final Logger logger = Logger.getLogger(ClusterTerminationService.class);
  private final ClusterConfJson clusterConfJson;
  private final String rootPath;

  public ClusterTerminationService(File configurationFile) throws IOException {
    this(JsonParser.getMapper().readValue(configurationFile, AutomationConf.class));
  }

  public ClusterTerminationService(AutomationConf automationConf) throws IOException {
    super(automationConf.getMailConf(), automationConf.getAccessKey(), automationConf.getSecretAccessKey());
    this.rootPath = automationConf.getRootPath();
    this.clusterConfJson = automationConf.getClusterConf();
  }

  @Override
  public void startService() {
    try {
      EMRClusterClient client = new EMRClusterClient(credential, notificationService, clusterConfJson);
      File folder = new File(rootPath);
      for (File f : folder.listFiles()) {
        String fileName = f.getName();
        Path filePath = f.toPath();
        if (fileName.startsWith(ClusterGenerationService.CLUSTER_STARTED_PREFIX)) {
          logger.info("Found cluster file " + filePath.toString());
          String jobFlowId = fileName.split("@")[1];
          logger.info("Shutting down the cluster with job flow id " + jobFlowId);
          client.terminateCluster(jobFlowId, true);
          logger.info("Deleting the file " + filePath.toString());
          Files.delete(filePath);
        }
      }
    } catch (Exception e) {
      String subject = "ClusterTerminationService Failed";
      notificationService.notify(subject, GeneralUtils.getStackTrace(e));
      throw new RuntimeException(subject, e);
    }
  }
}
