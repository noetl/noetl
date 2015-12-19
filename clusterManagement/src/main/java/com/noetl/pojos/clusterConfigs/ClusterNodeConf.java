package com.noetl.pojos.clusterConfigs;

public class ClusterNodeConf {
  private int count;
  private InstanceTypeConf instanceType;
  private String marketType;
  private String os;

  public int getCount() {
    return count;
  }

  public void setCount(int count) {
    this.count = count;
  }

  public InstanceTypeConf getInstanceType() {
    return instanceType;
  }

  public void setInstanceType(InstanceTypeConf instanceType) {
    this.instanceType = instanceType;
  }

  public String getMarketType() {
    return marketType;
  }

  public void setMarketType(String marketType) {
    this.marketType = marketType;
  }

  public String getOs() {
    return os;
  }

  public void setOs(String os) {
    this.os = os;
  }


}
