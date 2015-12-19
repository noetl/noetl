package com.noetl.pojos.serviceConfigs;

public class S3Conf {
  private String backUp;
  private String stage;

  public String getBackUp() {
    return backUp;
  }

  public void setBackUp(String backUp) {
    this.backUp = backUp;
  }

  public String getStage() {
    return stage;
  }

  public void setStage(String stage) {
    this.stage = stage;
  }

  @Override
  public String toString() {
    return "S3Conf{" +
      "backUp='" + backUp + '\'' +
      ", stage='" + stage + '\'' +
      '}';
  }
}
