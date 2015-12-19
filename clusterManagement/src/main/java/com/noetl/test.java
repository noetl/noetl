package com.noetl;

import com.amazonaws.auth.BasicAWSCredentials;
import com.noetl.automation.services.BaseService;
import com.noetl.automation.services.ConsoleNotificationService;
import com.noetl.aws.EMRClusterClient;
import com.noetl.parsers.JsonParser;
import com.noetl.pojos.AutomationConf;

import java.io.File;

public class test {

  public static void main(final String[] args) throws Exception {
    File confFile = new File("/Users/chenguo/Documents/noetl/dt/etl_prod/automation-pipeline/conf.json");
    final AutomationConf automationConf = JsonParser.getMapper().readValue(confFile, AutomationConf.class);

    BaseService baseService = new BaseService(new ConsoleNotificationService(), new BasicAWSCredentials(automationConf.getAccessKey(), automationConf.getSecretAccessKey())) {
      @Override
      public void startService() {
        try {
          EMRClusterClient client = new EMRClusterClient(credential, new ConsoleNotificationService(), automationConf.getClusterConf());
          String clusterId = client.startCluster();
          System.out.println(client.getMasterDNS(clusterId));
          //Thread.sleep(120000);
          //String clusterId = "j-3UQGMVRB418KI";
          //client.terminateCluster(clusterId, true);
          //System.out.println(client.getClusterState(clusterId));
        } catch (Exception e) {
          e.printStackTrace();
        }
      }
    };

    baseService.startService();
  }
}
