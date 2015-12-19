package com.noetl.pojos.serviceConfigs;

import java.util.List;

public class MonitorConfJson {
  private List<String> expectedFiles;
  private SFTPConf sftpConf;
  private S3Conf s3Conf;

  public List<String> getExpectedFiles() {
    return expectedFiles;
  }

  public void setExpectedFiles(List<String> expectedFiles) {
    this.expectedFiles = expectedFiles;
  }

  public SFTPConf getSftpConf() {
    return sftpConf;
  }

  public void setSftpConf(SFTPConf sftpConf) {
    this.sftpConf = sftpConf;
  }

  public S3Conf getS3Conf() {
    return s3Conf;
  }

  public void setS3Conf(S3Conf s3Conf) {
    this.s3Conf = s3Conf;
  }

  @Override
  public String toString() {
    return "MonitorConfJson{" +
      "expectedFiles=" + expectedFiles +
      ", sftpConf=" + sftpConf +
      ", s3Conf=" + s3Conf +
      '}';
  }
}
