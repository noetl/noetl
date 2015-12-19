package com.noetl.aws;

import com.amazonaws.auth.AWSCredentials;
import com.amazonaws.regions.RegionUtils;
import com.amazonaws.services.elasticmapreduce.AmazonElasticMapReduceClient;
import com.amazonaws.services.elasticmapreduce.model.Cluster;
import com.amazonaws.services.elasticmapreduce.model.DescribeClusterRequest;
import com.amazonaws.services.elasticmapreduce.model.DescribeClusterResult;
import com.amazonaws.services.elasticmapreduce.model.TerminateJobFlowsRequest;
import com.noetl.automation.services.INotificationService;
import com.noetl.pojos.clusterConfigs.ClusterConfJson;
import org.apache.log4j.Logger;

public class EMRClusterClient {

  private final static Logger logger = Logger.getLogger(EMRClusterClient.class);
  private final AmazonElasticMapReduceClient awsEMRClient;
  private final INotificationService notifier;
  private final ClusterConfJson clusterConfJson;

  public EMRClusterClient(AWSCredentials credential, INotificationService notifier, ClusterConfJson clusterConfJson) {
    this.notifier = notifier;
    this.clusterConfJson = clusterConfJson;
    awsEMRClient = new AmazonElasticMapReduceClient(credential);
    awsEMRClient.setRegion(RegionUtils.getRegion(clusterConfJson.getRegion()));
  }

  public String startCluster() {
    logger.info("Starting cluster...");
    return new EMRClusterBuilder(awsEMRClient, notifier, clusterConfJson).build();
  }

  public String getClusterState(String jobFlowId) {
    return getCluster(jobFlowId).getStatus().getState();
  }

  public Cluster getCluster(String jobFlowId) {
    DescribeClusterRequest request = new DescribeClusterRequest();
    request.setClusterId(jobFlowId);
    DescribeClusterResult requestResult = awsEMRClient.describeCluster(request);
    return requestResult.getCluster();
  }

  public void terminateCluster(String jobFlowId, boolean waitForCompletion) throws InterruptedException {
    logger.info("Terminating cluster...");
    TerminateJobFlowsRequest request = new TerminateJobFlowsRequest();
    request.withJobFlowIds(jobFlowId);
    awsEMRClient.terminateJobFlows(request);
    if (waitForCompletion) {
      waitForCompletion(jobFlowId);
    }
  }

  private void waitForCompletion(String jobFlow) throws InterruptedException {
    Cluster cluster;
    int waitTime;
    long startTime = System.currentTimeMillis();
    do {
      cluster = getCluster(jobFlow);
      String state = cluster.getStatus().getState();
      waitTime = getWaitTime(state);
      if (waitTime >= 0) {
        throw new RuntimeException("Unexpected starting of the cluster " + jobFlow);
      }
      if (waitTime == Integer.MIN_VALUE) {
        String msg = String.format("Cluster %s has been terminated.", jobFlow);
        logger.info(msg);
        notifier.notify("Cluster has been terminated", msg);
        return;
      }
      logger.info("Waiting for cluster to terminate...");
      Thread.sleep(-1 * waitTime);
      if (System.currentTimeMillis() - startTime > 10800000)
        throw new RuntimeException("Fail to terminate cluster within 30 minutes.");
    } while (true);
  }

  public String getMasterDNSImmediately(String jobFlow) throws InterruptedException {
    logger.info("Getting cluster master DNS...");
    Cluster cluster = getCluster(jobFlow);
    String state = cluster.getStatus().getState();
    int waitTime = getWaitTime(state);

    if (waitTime > 0)
      return "Cluster Not Ready. Current State: " + state;
    if (waitTime < 0) {
      logger.info("Cluster is being or has been terminated!");
      return "";
    }
    notifier.notify("Cluster is ready",
      String.format("Cluster %s has been started.", jobFlow));
    return cluster.getMasterPublicDnsName();
  }

  public String getMasterDNS(String jobFlow) throws InterruptedException {
    logger.info("Getting cluster master DNS...");
    Cluster cluster;
    int waitTime;
    do {
      cluster = getCluster(jobFlow);
      String state = cluster.getStatus().getState();
      waitTime = getWaitTime(state);
      if (waitTime < 0) {
        logger.info("Cluster is being or has been terminated!");
        return "";
      }
      logger.info(String.format("State of cluster: %s. Sleeping for %s milliseconds...",
        state, waitTime));
      Thread.sleep(waitTime);
    } while (waitTime != 0);
    String masterPublicDnsName = cluster.getMasterPublicDnsName();
    String msg = String.format("Cluster %s has been started.\nMaster public DNS name is %s", jobFlow, masterPublicDnsName);
    logger.info(msg);
    notifier.notify("Cluster is ready", msg);
    return masterPublicDnsName;
  }

  private int getWaitTime(String state) {
    switch (state) {
      case "STARTING":
      case "PROVISIONING": //provisioning step takes 3m for each node.
        return 480000; //wait 8m
      case "BOOTSTRAPPING": //bootstrapping takes 4m for one node.
        return 240000; //wait 4m
      case "RUNNING":  //running takes 4m for each node.
        return 60000;  //wait 1m
      case "WAITING":
        return 0;
      case "TERMINATING":
        return -10000;
      case "TERMINATED":
      case "TERMINATED_WITH_ERRORS":
        return Integer.MIN_VALUE;
      default:
        throw new RuntimeException(String.format("Unknown cluster state: %s. Need to add the new state to code.", state));
    }
  }
}
