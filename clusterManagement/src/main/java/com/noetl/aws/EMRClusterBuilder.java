package com.noetl.aws;

import com.amazonaws.services.elasticmapreduce.AmazonElasticMapReduceClient;
import com.amazonaws.services.elasticmapreduce.model.BootstrapActionConfig;
import com.amazonaws.services.elasticmapreduce.model.InstanceGroupConfig;
import com.amazonaws.services.elasticmapreduce.model.InstanceRoleType;
import com.amazonaws.services.elasticmapreduce.model.JobFlowInstancesConfig;
import com.amazonaws.services.elasticmapreduce.model.MarketType;
import com.amazonaws.services.elasticmapreduce.model.RunJobFlowRequest;
import com.amazonaws.services.elasticmapreduce.model.RunJobFlowResult;
import com.amazonaws.services.elasticmapreduce.model.ScriptBootstrapActionConfig;
import com.amazonaws.services.elasticmapreduce.model.StepConfig;
import com.amazonaws.services.elasticmapreduce.model.SupportedProductConfig;
import com.amazonaws.services.elasticmapreduce.util.StepFactory;
import com.noetl.automation.services.INotificationService;
import com.noetl.pojos.clusterConfigs.BootStrapConf;
import com.noetl.pojos.clusterConfigs.ClusterConf;
import com.noetl.pojos.clusterConfigs.ClusterConfJson;
import com.noetl.pojos.clusterConfigs.ClusterNodeConf;
import com.noetl.pojos.clusterConfigs.InstanceTypeConf;
import com.noetl.pojos.clusterConfigs.StepConfigConf;
import com.noetl.utils.GeneralUtils;
import org.apache.log4j.Logger;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;

public class EMRClusterBuilder {
  private final static Logger logger = Logger.getLogger(EMRClusterBuilder.class);
  private final AmazonElasticMapReduceClient awsEMRClient;
  private final INotificationService notifier;
  private final ClusterConfJson clusterConfJson;

  public EMRClusterBuilder(AmazonElasticMapReduceClient awsEMRClient, INotificationService notifier, ClusterConfJson clusterConfJson) {
    this.awsEMRClient = awsEMRClient;
    this.notifier = notifier;
    this.clusterConfJson = clusterConfJson;
  }

  public String build() {
    RunJobFlowResult result = awsEMRClient.runJobFlow(configureRequest());
    String jobFlowId = result.getJobFlowId();
    logger.info("Starting cluster with id:" + jobFlowId);
    return jobFlowId;
  }

  private RunJobFlowRequest configureRequest() {
    logger.info("Start configuring the cluster...");

    ClusterConf clusterConf = clusterConfJson.getCluster();

    RunJobFlowRequest request = new RunJobFlowRequest()
      .withName(clusterConf.getName())
      .withAmiVersion(clusterConf.getVersion())
      .withSteps(configureStepConfigs(clusterConf.getStepConfigs()))
      .withNewSupportedProducts(configureProducts(clusterConf.getInstalls()))
      .withBootstrapActions(configureBootStraps(clusterConf.getBootStraps()))
      .withLogUri(clusterConf.getLogURI())
      .withServiceRole(clusterConf.getServiceRole())
      .withJobFlowRole(clusterConf.getJobFlowRole())
      .withInstances(
        new JobFlowInstancesConfig()
          .withInstanceGroups(configureClusterNodes(clusterConf.getMasterNode(), clusterConf.getCoreNode()))
          .withKeepJobFlowAliveWhenNoSteps(true)
          .withEc2KeyName(clusterConfJson.getKey())
          .withEc2SubnetId(clusterConf.getSubnet())
      );
    return request;
  }

  private List<BootstrapActionConfig> configureBootStraps(List<BootStrapConf> bootStrapConfs) {
    logger.info("Configuring boot straps...");
    List<BootstrapActionConfig> bootStraps = new ArrayList<>();
    for (BootStrapConf bootStrapConf : bootStrapConfs) {
      BootstrapActionConfig config = new BootstrapActionConfig()
        .withName(bootStrapConf.getName())
        .withScriptBootstrapAction(new ScriptBootstrapActionConfig()
          .withPath(bootStrapConf.getScript()));
      bootStraps.add(config);
    }
    return bootStraps;
  }

  private List<StepConfig> configureStepConfigs(List<StepConfigConf> stepConfigConfs) {
    logger.info("Configuring step configs...");
    StepFactory stepFactory = new StepFactory();
    List<StepConfig> ret = new ArrayList<>();
    StepConfig enableDebugging = new StepConfig()
      .withName("Enable debugging")
      .withActionOnFailure("TERMINATE_JOB_FLOW")
      .withHadoopJarStep(stepFactory.newEnableDebuggingStep());
    ret.add(enableDebugging); //Add this for all clusters.

    if (stepConfigConfs.size() > 0)
      throw new RuntimeException("The step configs feature is currently not supported.");
    /*
    for (com.noetl.pojos.clusterConfigs.StepConfig stepConfig : stepConfigs) {
      if (stepConfig.isUseDefault()) {
        StepConfig sc = new StepConfig()
          .withName(stepConfig.getName())
          .withActionOnFailure("TERMINATE_JOB_FLOW")
          .withHadoopJarStep(stepFactory.newInstallHiveStep());
      } else {
        throw new RuntimeException("The feature(useDefault=false for stepConfig) is currently not supported.");
      }
      ret.add(sc);
    }
    */
    return ret;
  }

  private static Collection<SupportedProductConfig> configureProducts(List<String> installs) {
    logger.info("Configuring products to be installed...");
    ArrayList<SupportedProductConfig> supportedProductConfigs = new ArrayList<>();
    for (String product : installs) {
      supportedProductConfigs.add(new SupportedProductConfig().withName(product));
    }
    return supportedProductConfigs;
  }

  private Collection<InstanceGroupConfig> configureClusterNodes(ClusterNodeConf masterNode, ClusterNodeConf coreNode) {
    logger.info("Configuring cluster nodes...");
    Collection<InstanceGroupConfig> InstanceGroup = new ArrayList<>();
    InstanceGroupConfig master = configureClusterNode(masterNode, InstanceRoleType.MASTER);
    InstanceGroup.add(master);

    InstanceGroupConfig core = configureClusterNode(coreNode, InstanceRoleType.CORE);
    InstanceGroup.add(core);
    return InstanceGroup;
  }

  private InstanceGroupConfig configureClusterNode(ClusterNodeConf nodeConfig, InstanceRoleType roleType) {
    String marketTypeString = nodeConfig.getMarketType().toLowerCase();
    MarketType marketType;
    switch (marketTypeString) {
      case "on_demand":
        marketType = MarketType.ON_DEMAND;
        break;
      case "spot":
        marketType = MarketType.SPOT;
        break;
      default:
        throw new RuntimeException("Unknown market type value " + marketTypeString);
    }

    InstanceTypeConf instanceTypeConf = nodeConfig.getInstanceType();
    String type = instanceTypeConf.getType().toLowerCase();
    String instanceTypeString;
    EMRBid bid = null;
    switch (type) {
      case "size":
        instanceTypeString = instanceTypeConf.getSize(); //On_demand
        if (marketType.equals(MarketType.SPOT)) {
          bid = getEMRBid(nodeConfig);
        }
        break;
      case "tier":
        bid = getEMRBid(nodeConfig);
        instanceTypeString = bid.getSize();
        break;
      default:
        throw new RuntimeException("Unknown instance type category " + type);
    }

    InstanceGroupConfig instanceGroupConfig = new InstanceGroupConfig()
      .withInstanceCount(nodeConfig.getCount())
      .withInstanceRole(roleType)
      .withInstanceType(instanceTypeString)
      .withMarket(marketType);
    if (marketType.equals(MarketType.SPOT))
      instanceGroupConfig.withBidPrice(bid.getBidPrice());

    return instanceGroupConfig;
  }

  private EMRBid getEMRBid(ClusterNodeConf nodeConf) {
    InstanceTypeConf instanceTypeConf = nodeConf.getInstanceType();
    String type = instanceTypeConf.getType().toLowerCase();
    EMRBid bid;
    try {
      logger.info("Getting best bid price for nodes...");
      EMRBidder emrBidder = new EMRBidder(clusterConfJson.getSpotPriceURL(), clusterConfJson.getCurrency());
      switch (type) {
        case "tier":
          bid = emrBidder.bestBidByTier(clusterConfJson.getRegion(), nodeConf.getOs(), clusterConfJson.getTiers().get(instanceTypeConf.getTier()));
          break;
        case "size":
          bid = emrBidder.getSpotForSize(clusterConfJson.getRegion(), nodeConf.getOs(), instanceTypeConf.getSize());
          break;
        default:
          throw new RuntimeException("Unknown instance type category " + type);
      }
      logger.info(String.format("Bidding for size %s at price %s",
        bid.getSize(), bid.getBidPrice()));
      return bid;
    } catch (IOException e) {
      String subject = "Fail to create a bid price for EMR slaves";
      notifier.notify(subject, GeneralUtils.getStackTrace(e));
      throw new RuntimeException(subject, e);
    }
  }
}
