package com.noetl.pojos.clusterConfigs;

import java.util.List;
import java.util.Map;

public class ClusterConfJson {
  private String region;
  private String spotPriceURL;
  private String currency;
  private String key;
  private ClusterConf cluster;
  private Map<String, List<EMRPremium>> tiers;

  public String getRegion() {
    return region;
  }

  public void setRegion(String region) {
    this.region = region;
  }

  public String getCurrency() {
    return currency;
  }

  public String getKey() {
    return key;
  }

  public void setKey(String key) {
    this.key = key;
  }

  public void setCurrency(String currency) {
    this.currency = currency;
  }

  public ClusterConf getCluster() {
    return cluster;
  }

  public void setCluster(ClusterConf cluster) {
    this.cluster = cluster;
  }

  public Map<String, List<EMRPremium>> getTiers() {
    return tiers;
  }

  public void setTiers(Map<String, List<EMRPremium>> tiers) {
    this.tiers = tiers;
  }

  public String getSpotPriceURL() {
    return spotPriceURL;
  }

  public void setSpotPriceURL(String spotPriceURL) {
    this.spotPriceURL = spotPriceURL;
  }
}
