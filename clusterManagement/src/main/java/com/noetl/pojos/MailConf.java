package com.noetl.pojos;

import java.util.List;

public class MailConf {
  private String host;
  private int port;
  private String sender;
  private String senderPassword;
  private List<String> recipients;
  private String authentication;
  private String starttls;

  public String getHost() {
    return host;
  }

  public void setHost(String host) {
    this.host = host;
  }

  public int getPort() {
    return port;
  }

  public void setPort(int port) {
    this.port = port;
  }

  public String getSender() {
    return sender;
  }

  public void setSender(String sender) {
    this.sender = sender;
  }

  public String getSenderPassword() {
    return senderPassword;
  }

  public void setSenderPassword(String senderPassword) {
    this.senderPassword = senderPassword;
  }

  public List<String> getRecipients() {
    return recipients;
  }

  public void setRecipients(List<String> recipients) {
    this.recipients = recipients;
  }

  public String getAuthentication() {
    return authentication;
  }

  public void setAuthentication(String authentication) {
    this.authentication = authentication;
  }

  public String getStarttls() {
    return starttls;
  }

  public void setStarttls(String starttls) {
    this.starttls = starttls;
  }

  @Override
  public String toString() {
    return "MailConf{" +
      "host='" + host + '\'' +
      ", port=" + port +
      ", sender='" + sender + '\'' +
      ", senderPassword='" + senderPassword + '\'' +
      ", recipients=" + recipients +
      ", authentication='" + authentication + '\'' +
      ", starttls='" + starttls + '\'' +
      '}';
  }
}
