package com.noetl.pojos.clusterConfigs;

import java.util.List;

public class ClusterConf {
  private String name;
  private String subnet;
  private String version;
  private String serviceRole;
  private String jobFlowRole;
  private String logURI;
  private ClusterNodeConf masterNode;
  private ClusterNodeConf coreNode;
  private List<String> installs;
  private List<StepConfigConf> stepConfigs;
  private List<BootStrapConf> bootStraps;

  public String getName() {
    return name;
  }

  public void setName(String name) {
    this.name = name;
  }

  public String getSubnet() {
    return subnet;
  }

  public void setSubnet(String subnet) {
    this.subnet = subnet;
  }

  public String getVersion() {
    return version;
  }

  public void setVersion(String version) {
    this.version = version;
  }

  public String getServiceRole() {
    return serviceRole;
  }

  public void setServiceRole(String serviceRole) {
    this.serviceRole = serviceRole;
  }

  public String getJobFlowRole() {
    return jobFlowRole;
  }

  public void setJobFlowRole(String jobFlowRole) {
    this.jobFlowRole = jobFlowRole;
  }

  public String getLogURI() {
    return logURI;
  }

  public void setLogURI(String logURI) {
    this.logURI = logURI;
  }

  public ClusterNodeConf getMasterNode() {
    return masterNode;
  }

  public void setMasterNode(ClusterNodeConf masterNode) {
    this.masterNode = masterNode;
  }

  public ClusterNodeConf getCoreNode() {
    return coreNode;
  }

  public void setCoreNode(ClusterNodeConf coreNode) {
    this.coreNode = coreNode;
  }

  public List<String> getInstalls() {
    return installs;
  }

  public void setInstalls(List<String> installs) {
    this.installs = installs;
  }

  public List<StepConfigConf> getStepConfigs() {
    return stepConfigs;
  }

  public void setStepConfigs(List<StepConfigConf> stepConfigs) {
    this.stepConfigs = stepConfigs;
  }

  public List<BootStrapConf> getBootStraps() {
    return bootStraps;
  }

  public void setBootStraps(List<BootStrapConf> bootStraps) {
    this.bootStraps = bootStraps;
  }
}
