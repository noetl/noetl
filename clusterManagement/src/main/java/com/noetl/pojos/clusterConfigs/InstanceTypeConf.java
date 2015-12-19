package com.noetl.pojos.clusterConfigs;

public class InstanceTypeConf {
  private String type;
  private String size;
  private String tier;

  public String getType() {
    return type;
  }

  public void setType(String type) {
    this.type = type;
  }

  public String getSize() {
    return size;
  }

  public void setSize(String size) {
    this.size = size;
  }

  public String getTier() {
    return tier;
  }

  public void setTier(String tier) {
    this.tier = tier;
  }

  @Override
  public String toString() {
    return "InstanceTypeConf{" +
      "type='" + type + '\'' +
      ", size='" + size + '\'' +
      ", tier='" + tier + '\'' +
      '}';
  }
}
