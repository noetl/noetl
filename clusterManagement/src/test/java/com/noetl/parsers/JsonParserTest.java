package com.noetl.parsers;

import com.noetl.pojos.MailConf;
import com.noetl.pojos.clusterConfigs.BootStrapConf;
import com.noetl.pojos.clusterConfigs.ClusterConf;
import com.noetl.pojos.clusterConfigs.ClusterConfJson;
import com.noetl.pojos.clusterConfigs.ClusterNodeConf;
import com.noetl.pojos.clusterConfigs.EMRPremium;
import com.noetl.pojos.clusterConfigs.InstanceTypeConf;
import com.noetl.pojos.clusterConfigs.StepConfigConf;
import com.noetl.pojos.serviceConfigs.MonitorConfJson;
import org.junit.Test;

import java.io.InputStream;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;

public class JsonParserTest {
  @Test
  public void testParsingClusterConf() throws Exception {
    InputStream fileStream = this.getClass().getResourceAsStream("/confs/clusterConf_comprehensive.json");
    ClusterConfJson clusterConfJson = JsonParser.getMapper().readValue(fileStream, ClusterConfJson.class);
    assertEquals("us-west-2", clusterConfJson.getRegion());
    assertEquals("http://spot-price.s3.amazonaws.com/spot.js", clusterConfJson.getSpotPriceURL());
    assertEquals("USD", clusterConfJson.getCurrency());
    assertEquals("data-key", clusterConfJson.getKey());
    ClusterConf clusterConf = clusterConfJson.getCluster();
    assertEquals("italy", clusterConf.getName());
    assertEquals("subnet-id", clusterConf.getSubnet());
    assertEquals("3.10", clusterConf.getVersion());
    assertEquals("serviceRole", clusterConf.getServiceRole());
    assertEquals("jobFlowRole", clusterConf.getJobFlowRole());
    assertEquals("s3://aws-emr-lg/", clusterConf.getLogURI());
    ClusterNodeConf masterNode = clusterConf.getMasterNode();
    assertEquals(1, masterNode.getCount());
    InstanceTypeConf masterNodeInstanceTypeConf = masterNode.getInstanceType();
    assertEquals("size", masterNodeInstanceTypeConf.getType());
    assertEquals("m2.2xlarge", masterNodeInstanceTypeConf.getSize());
    assertEquals(null, masterNodeInstanceTypeConf.getTier());
    assertEquals("on_demand", masterNode.getMarketType());
    assertEquals("linux", masterNode.getOs());

    ClusterNodeConf coreNode = clusterConf.getCoreNode();
    assertEquals(1, coreNode.getCount());
    InstanceTypeConf coreNodeInstanceTypeConf = coreNode.getInstanceType();
    assertEquals("tier", coreNodeInstanceTypeConf.getType());
    assertEquals(null, coreNodeInstanceTypeConf.getSize());
    assertEquals("high", coreNodeInstanceTypeConf.getTier());
    assertEquals("spot", coreNode.getMarketType());
    assertEquals("linux", coreNode.getOs());

    assertArrayEquals(new String[]{"Spark", "Hive", "HBASE", "Hue", "Ganglia"},
      clusterConf.getInstalls().toArray(new String[clusterConf.getInstalls().size()]));

    List<StepConfigConf> stepConfigConfs = clusterConf.getStepConfigs();
    assertEquals(1, stepConfigConfs.size());
    StepConfigConf stepConfigConf = stepConfigConfs.get(0);
    assertEquals("Install Hive", stepConfigConf.getName());
    assertEquals(true, stepConfigConf.isUseDefault());
    assertEquals(new HashMap<String, Object>(), stepConfigConf.getHadoopJarStepConfigs());

    List<BootStrapConf> bootStrapConfs = clusterConf.getBootStraps();
    assertEquals(1, bootStrapConfs.size());
    BootStrapConf bootStrapConf = bootStrapConfs.get(0);
    assertEquals("Install HBase", bootStrapConf.getName());
    assertEquals("s3://elasticmapreduce/bootstrap-actions/setup-hbase", bootStrapConf.getScript());

    Map<String, List<EMRPremium>> tiers = clusterConfJson.getTiers();
    assertEquals(2, tiers.size());
    List<EMRPremium> highTier = tiers.get("high");
    assertEquals(3, highTier.size());
    EMRPremium highTier1 = highTier.get(0);
    assertEquals("m3.2xlarge", highTier1.getSize());
    assertEquals(0.14, highTier1.getPremium(), 1e-6);

    List<EMRPremium> mediumTier = tiers.get("medium");
    assertEquals(3, mediumTier.size());
    EMRPremium mediumTier1 = mediumTier.get(0);
    assertEquals("m2.2xlarge", mediumTier1.getSize());
    assertEquals(0.123, mediumTier1.getPremium(), 1e-6);
  }

  @Test
  public void testParsingServiceConf() throws Exception {
    InputStream fileStream = this.getClass().getResourceAsStream("/confs/monitorConf.json");
    MonitorConfJson monitorConfJson = JsonParser.getMapper().readValue(fileStream, MonitorConfJson.class);

    assertArrayEquals(new String[]{"New_Wamp", "New_Wamp_National", "custdata", "noetl_CD_IRA", "noetl_DDA", "noetl_INV", "noetl_SAV"},
      monitorConfJson.getExpectedFiles().toArray(new String[monitorConfJson.getExpectedFiles().size()]));

    assertEquals("/mnt/md0/companysftp/sftp_uploads", monitorConfJson.getSftpConf().getSource());
    assertEquals("/mnt/md0/companysftp/sftp_uploads", monitorConfJson.getSftpConf().getDestination());
    assertEquals("s3://noetl-company-auto/fresh/", monitorConfJson.getS3Conf().getBackUp());
    assertEquals("s3://noetl-company-auto/stage/", monitorConfJson.getS3Conf().getStage());
  }

  @Test
  public void testParsingMailConf() throws Exception {
    InputStream fileStream = this.getClass().getResourceAsStream("/confs/mailConf.json");
    MailConf mailConf = JsonParser.getMapper().readValue(fileStream, MailConf.class);
    assertEquals("smtp.office365.com", mailConf.getHost());
    assertEquals(587, mailConf.getPort());
    assertEquals("amsterdam.datateam@noetlsolutions.com", mailConf.getSender());
    assertEquals("#noetl15", mailConf.getSenderPassword());
    List<String> recipients = mailConf.getRecipients();
    assertEquals(1, recipients.size());
    String recipient0 = recipients.get(0);
    assertEquals("chen.guo@noetlsolutions.com", recipient0);
    assertEquals("true", mailConf.getAuthentication());
    assertEquals("true", mailConf.getStarttls());
  }
}
