package com.noetl.automation.services;

public class ConsoleNotificationService implements INotificationService {
  @Override
  public void notify(String subject, String text) {
    System.out.println("Subject:\t" + subject);
    System.out.println("Body:\n\t" + text);
  }
}
