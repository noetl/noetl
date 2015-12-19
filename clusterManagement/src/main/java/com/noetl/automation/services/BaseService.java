package com.noetl.automation.services;

import com.amazonaws.auth.AWSCredentials;
import com.amazonaws.auth.BasicAWSCredentials;
import com.noetl.pojos.MailConf;

public abstract class BaseService {
  protected final INotificationService notificationService;
  protected final AWSCredentials credential;

  public BaseService(INotificationService notificationService, AWSCredentials credential) {
    this.notificationService = notificationService;
    this.credential = credential;
  }

  public BaseService(MailConf mailConf, String accessKey, String secretAccessKey) {
    notificationService = new MailNotificationService(mailConf);
    credential = new BasicAWSCredentials(accessKey, secretAccessKey);
  }

  public abstract void startService();
}
