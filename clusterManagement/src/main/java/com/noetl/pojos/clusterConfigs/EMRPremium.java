package com.noetl.pojos.clusterConfigs;

public class EMRPremium {
  private String size;
  private Double premium;

  public EMRPremium() {
  }

  public EMRPremium(String size, Double premium) {
    this.size = size;
    this.premium = premium;
  }

  public String getSize() {
    return size;
  }

  public void setSize(String size) {
    this.size = size;
  }

  public Double getPremium() {
    return premium;
  }

  public void setPremium(Double premium) {
    this.premium = premium;
  }

  @Override
  public String toString() {
    return "EMRPremium{" +
      "size='" + size + '\'' +
      ", premium=" + premium +
      '}';
  }
}

