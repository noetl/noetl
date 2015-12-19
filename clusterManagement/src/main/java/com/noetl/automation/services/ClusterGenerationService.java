package com.noetl.automation.services;

import com.amazonaws.auth.AWSCredentials;
import com.amazonaws.services.s3.AmazonS3Client;
import com.amazonaws.services.s3.model.ListObjectsRequest;
import com.amazonaws.services.s3.model.ObjectListing;
import com.amazonaws.services.s3.model.S3ObjectSummary;
import com.amazonaws.util.StringUtils;
import com.noetl.aws.EMRClusterClient;
import com.noetl.aws.utils.AWSS3Util;
import com.noetl.parsers.JsonParser;
import com.noetl.pojos.AutomationConf;
import com.noetl.pojos.clusterConfigs.ClusterConfJson;
import com.noetl.pojos.serviceConfigs.MonitorConfJson;
import com.noetl.utils.GeneralUtils;
import org.apache.commons.io.FileUtils;
import org.apache.log4j.Logger;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;

public class ClusterGenerationService extends BaseService {

  private static final Logger logger = Logger.getLogger(ClusterGenerationService.class);
  public static final String CLUSTER_STARTED_PREFIX = "ClusterStarted_JFId@";
  private final ClusterConfJson clusterConfJson;
  private final MonitorConfJson monitorConfJson;
  private final String rootPath;

  ClusterGenerationService(ClusterConfJson clusterConfJson, MonitorConfJson serviceConf, INotificationService notificationService, AWSCredentials credential) {
    super(notificationService, credential);
    this.clusterConfJson = clusterConfJson;
    this.monitorConfJson = serviceConf;
    this.rootPath = "";
  }

  public ClusterGenerationService(File configurationFile) throws IOException {
    this(JsonParser.getMapper().readValue(configurationFile, AutomationConf.class));
  }

  public ClusterGenerationService(AutomationConf automationConf) throws IOException {
    super(automationConf.getMailConf(), automationConf.getAccessKey(), automationConf.getSecretAccessKey());
    this.rootPath = automationConf.getRootPath();
    this.clusterConfJson = automationConf.getClusterConf();
    this.monitorConfJson = automationConf.getMonitorConf();
  }

  @Override
  public void startService() {
    try {
      ArrayList<String> filesForCluster = new ArrayList<>();
      if (clusterStarted())
        return;
      if (monitor(filesForCluster)) {
        EMRClusterClient client = new EMRClusterClient(credential, notificationService, clusterConfJson);
        String filesForClusterString = StringUtils.join(",", filesForCluster.toArray(new String[filesForCluster.size()]));
        logger.info("Those files will be used to for the cluster.\n" + filesForClusterString);
        String jobFlowId = client.startCluster();
        String fileName = CLUSTER_STARTED_PREFIX + jobFlowId;
        Path path = Paths.get(rootPath, fileName);
        logger.info("Sent request to start cluster. Creating file " + path.toString());
        Files.createFile(path);
        File file = new File(path.toString());
        String writeToFile = String.format("Master DNS:%s\nFiles for pipeline:%s",
          client.getMasterDNS(jobFlowId), filesForClusterString);
        FileUtils.writeStringToFile(file, writeToFile);
        logger.info("Cluster has been started. Have written information to file " + path.toString());
      }
    } catch (Exception e) {
      String subject = "ClusterGenerationService Failed";
      notificationService.notify(subject, GeneralUtils.getStackTrace(e));
      throw new RuntimeException(subject, e);
    }
  }

  private boolean clusterStarted() {
    File folder = new File(rootPath);
    for (File f : folder.listFiles()) {
      if (f.getName().startsWith(CLUSTER_STARTED_PREFIX)) {
        logger.info("Cluster already started. Found file " + f.getName());
        return true;
      }
    }
    return false;
  }

  public boolean monitor(ArrayList<String> filesForCluster) {
    return monitor(constructFileMappings(), filesForCluster);
  }

  boolean monitor(HashMap<String, List<String>> fileMappings, ArrayList<String> filesForCluster) {
    if (fileMappings == null || fileMappings.isEmpty()) {
      logger.info("File mappings are empty.");
      return false;
    }
    int expectedFilesCount = fileMappings.size();
    filesForCluster.clear();

    int allFileGroupsCount = 0;
    ArrayList<String> allAvailableFiles = new ArrayList<>();
    boolean dataFilesIncomplete = false;
    ArrayList<ArrayList<String>> allFileGroups = new ArrayList<>();
    for (Map.Entry<String, List<String>> mapping : fileMappings.entrySet()) {
      String key = mapping.getKey();
      List<String> dataFiles = mapping.getValue();

      if (dataFiles == null || dataFiles.isEmpty()) {
        logger.info("First un-matching file found for " + key);
        return false;
      }
      allAvailableFiles.addAll(dataFiles);
      int currentGroupsCount = dataFiles.size();
      if (allFileGroupsCount == 0) {
        for (int i = 0; i < currentGroupsCount; ++i) {
          allFileGroups.add(new ArrayList<String>(expectedFilesCount));
        }
        allFileGroupsCount = currentGroupsCount;
      }
      if (currentGroupsCount != allFileGroupsCount) {
        //Maybe you get Aug and Sept data for one file, but only Aug data for other files
        //In this case, there will be incomplete data file groups.
        dataFilesIncomplete = true;
      }
      if (currentGroupsCount > allFileGroupsCount) {
        //expand allFileGroups to include the new groups.
        for (int i = 0; i < currentGroupsCount - allFileGroupsCount; ++i) {
          allFileGroups.add(new ArrayList<String>(expectedFilesCount));
        }
      }
      Collections.sort(dataFiles);
      for (int i = 0; i < currentGroupsCount; ++i) {
        allFileGroups.get(i).add(dataFiles.get(i));
      }
    }

    for (ArrayList<String> groupOfFile : allFileGroups) {
      if (groupOfFile.size() == expectedFilesCount) {
        filesForCluster.addAll(groupOfFile);
      }
    }

    String warning = "";
    if (dataFilesIncomplete) {
      warning = "\n***********************************************************************************\n" +
        "**** Warning: Find incomplete file groups! ****\n" +
        "**** Please double check the files used for the cluster meet your expectation. ****\n" +
        "***********************************************************************************\n\n";
    }

    String msg = String.format("%sAll data files available:\n%s\n\nFiles for cluster:\n%s",
      warning,
      StringUtils.join("\t\n", allAvailableFiles.toArray(new String[allAvailableFiles.size()])),
      StringUtils.join("\t\n", filesForCluster.toArray(new String[filesForCluster.size()])));
    logger.info(msg);
    notificationService.notify("Files are ready for the pipeline", msg);
    return true;
  }

  /**
   * @return fileKey - relevant Files
   */
  private HashMap<String, List<String>> constructFileMappings() {
    List<String> expectedFiles = monitorConfJson.getExpectedFiles();
    HashSet<String> uniqueFiles = new HashSet<>(expectedFiles);
    if (expectedFiles.size() != uniqueFiles.size())
      throw new RuntimeException("Found duplications in expected file configuration:\n\t" + StringUtils.join(",", expectedFiles.toArray(new String[expectedFiles.size()])));

    logger.info("Looking for the following files:\n"
      + StringUtils.join(",", expectedFiles.toArray(new String[expectedFiles.size()])));
    HashMap<String, List<String>> fileMapping = new HashMap<>();
    for (String file : expectedFiles) {
      fileMapping.put(file, new ArrayList<String>());
    }

    ArrayList<String> allFiles = getAllFiles();
    for (String prefix : allFiles) {
      logger.info("Find prefix: " + prefix);
      int fileNameStarts = prefix.lastIndexOf("/");
      String fileName = prefix.substring(fileNameStarts + 1);
      for (String cef : expectedFiles) {
        if (fileName.contains(cef)) {
          fileMapping.get(cef).add(fileName);
          break;
        }
      }
    }
    return fileMapping;
  }

  /**
   * @return all files under the S3 monitoring path
   */
  private ArrayList<String> getAllFiles() {
    ArrayList<String> allFiles = new ArrayList<>();
    AmazonS3Client s3client = new AmazonS3Client(credential);
    String s3path = monitorConfJson.getS3Conf().getStage();
    String bucket = AWSS3Util.getBucketName(s3path);
    String key = AWSS3Util.getKey(s3path);

    ListObjectsRequest listObjectsRequest = new ListObjectsRequest().withBucketName(bucket).withPrefix(key);
    ObjectListing objectListing = s3client.listObjects(listObjectsRequest);

    for (S3ObjectSummary objectSummary : objectListing.getObjectSummaries()) {
      allFiles.add(objectSummary.getKey());
    }
    return allFiles;
  }
}
