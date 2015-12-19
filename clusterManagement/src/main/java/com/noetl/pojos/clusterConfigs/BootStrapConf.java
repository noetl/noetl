package com.noetl.pojos.clusterConfigs;

public class BootStrapConf {
  private String name;
  private String script;

  public String getName() {
    return name;
  }

  public void setName(String name) {
    this.name = name;
  }

  public String getScript() {
    return script;
  }

  public void setScript(String script) {
    this.script = script;
  }

  @Override
  public String toString() {
    return "BootStrapConf{" +
      "name='" + name + '\'' +
      ", script='" + script + '\'' +
      '}';
  }
}
