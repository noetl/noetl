package com.noetl.pojos.clusterConfigs;

import java.util.Map;

public class StepConfigConf {
  private String name;
  private boolean useDefault;
  private Map<String, Object> hadoopJarStepConfigs;

  public String getName() {
    return name;
  }

  public void setName(String name) {
    this.name = name;
  }

  public boolean isUseDefault() {
    return useDefault;
  }

  public void setUseDefault(boolean useDefault) {
    this.useDefault = useDefault;
  }

  public Map<String, Object> getHadoopJarStepConfigs() {
    return hadoopJarStepConfigs;
  }

  public void setHadoopJarStepConfigs(Map<String, Object> hadoopJarStepConfigs) {
    this.hadoopJarStepConfigs = hadoopJarStepConfigs;
  }

  @Override
  public String toString() {
    return "StepConfigConf{" +
      "name='" + name + '\'' +
      ", useDefault=" + useDefault +
      ", hadoopJarStepConfigs=" + hadoopJarStepConfigs +
      '}';
  }
}
