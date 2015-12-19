package com.noetl.automation.services;

import com.noetl.pojos.MailConf;
import org.apache.log4j.Logger;

import javax.mail.Message;
import javax.mail.MessagingException;
import javax.mail.PasswordAuthentication;
import javax.mail.Session;
import javax.mail.Transport;
import javax.mail.internet.InternetAddress;
import javax.mail.internet.MimeMessage;
import java.util.Arrays;
import java.util.List;
import java.util.Properties;

public class MailNotificationService implements INotificationService {

  private final static Logger logger = Logger.getLogger(MailNotificationService.class);
  private final MailConf mailConf;

  public MailNotificationService(MailConf mailConf) {

    this.mailConf = mailConf;
  }

  public void notify(String subject, String text) {
    try {
      Session session = initialization();
      Message message = new MimeMessage(session);
      message.setFrom(new InternetAddress(mailConf.getSender()));
      List<String> recipientList = mailConf.getRecipients();

      for (String receiver : recipientList) {
        message.setRecipients(Message.RecipientType.TO, InternetAddress.parse(receiver));
        message.setSubject(subject);
        message.setText(text);
        Transport.send(message);
      }
      logger.info("Sent email to: " + Arrays.toString(recipientList.toArray()));
    } catch (MessagingException e) {
      throw new RuntimeException(e);
    }
  }

  private Session initialization() {
    Properties props = new Properties();
    //It must be a STRING!!!!!
    props.put("mail.smtp.auth", mailConf.getAuthentication());
    //It must be a STRING!!!!!
    props.put("mail.smtp.starttls.enable", mailConf.getStarttls());
    props.put("mail.smtp.host", mailConf.getHost());
    props.put("mail.smtp.port", mailConf.getPort());

    Session session = Session.getDefaultInstance(props,
      new javax.mail.Authenticator() {
        protected PasswordAuthentication getPasswordAuthentication() {
          return new PasswordAuthentication
            (mailConf.getSender(), mailConf.getSenderPassword());
        }
      });
    logger.info("Finish mail service setup.");
    return session;
  }
}
