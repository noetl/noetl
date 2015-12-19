package com.noetl.automation.services;

import com.noetl.parsers.JsonParser;
import com.noetl.pojos.AutomationConf;
import com.noetl.pojos.serviceConfigs.MonitorConfJson;
import com.noetl.pojos.serviceConfigs.S3Conf;
import com.noetl.pojos.serviceConfigs.SFTPConf;
import com.noetl.utils.DateTimeUtil;
import com.noetl.utils.FileOps;
import com.noetl.utils.GeneralUtils;
import org.apache.log4j.Logger;

import java.io.File;
import java.io.IOException;
import java.nio.file.FileSystems;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardWatchEventKinds;
import java.nio.file.WatchEvent;
import java.nio.file.WatchKey;
import java.nio.file.WatchService;

public class SFTPToS3Service extends BaseService {
  private static final Logger logger = Logger.getLogger(SFTPToS3Service.class);
  private final FileOps fileOps;
  private final MonitorConfJson monitorConfJson;
  private final SFTPConf sftpConf;
  private final S3Conf s3Conf;

  public SFTPToS3Service(File configurationFile) throws IOException {
    this(JsonParser.getMapper().readValue(configurationFile, AutomationConf.class));
  }

  public SFTPToS3Service(AutomationConf automationConf) throws IOException {
    super(automationConf.getMailConf(), automationConf.getAccessKey(), automationConf.getSecretAccessKey());
    fileOps = new FileOps(notificationService);
    monitorConfJson = automationConf.getMonitorConf();
    sftpConf = monitorConfJson.getSftpConf();
    s3Conf = monitorConfJson.getS3Conf();
  }

  @Override
  public void startService() {
    try {
      String monitoringPath = sftpConf.getSource();
      Path faxFolder = Paths.get(monitoringPath);
      WatchService watchService = FileSystems.getDefault().newWatchService();
      faxFolder.register(watchService, StandardWatchEventKinds.ENTRY_CREATE);
      String s3Dest1 = s3Conf.getBackUp();
      String s3Dest2 = s3Conf.getStage();
      String localDestinationRoot = sftpConf.getDestination();
      boolean valid;
      logger.info("SFTP to S3 service started...");
      do {
        WatchKey watchKey = watchService.take();
        for (WatchEvent event : watchKey.pollEvents()) {
          // !!!! Note !!!!
          // watchKey.pollEvents() is a blockage call.
          // it only returns when there is an event. Use screen rather than crontab.
          if (StandardWatchEventKinds.ENTRY_CREATE.equals(event.kind())) {
            File newFile = new File(monitoringPath, event.context().toString());
            checkForCompletion(newFile);
            String timeString = DateTimeUtil.getCurrentTimeDefault();
            String destinationSuffix = "/" + DateTimeUtil.getCurrentTimeYMD();
            if (newFile.isFile()) {
              logger.info(String.format("New file '%s' detected at %s", newFile.toString(), timeString));
              fileOps.uploadFileToS3(newFile, new String[]{s3Dest1, s3Dest2}, credential);
              fileOps.moveFileLocal(newFile, localDestinationRoot + destinationSuffix);
            } else {
              String folderName = newFile.getName();
              if (DateTimeUtil.canParseYMD(folderName))
                //Do not move date folder. It is created by code.
                continue;
              logger.info(String.format("New directory '%s' detected at %s", newFile.toString(), timeString));
              fileOps.uploadFolderS3(newFile, new String[]{s3Dest1, s3Dest2}, credential);
              fileOps.moveDirectoryLocal(newFile, localDestinationRoot + destinationSuffix);
            }
          }
        }
        valid = watchKey.reset();
        if (!valid) {
          logger.info(String.format("Key reset invalid. Exiting monitoring for %s.", monitoringPath));
          break;
        }
      } while (valid);
    } catch (IOException e) {
      String errorMsg = "Path under monitoring may not exist.\n" + GeneralUtils.getStackTrace(e);
      String subject = "SFTPToS3Service Failed";
      notificationService.notify(subject, errorMsg);
      throw new RuntimeException(subject, e);
    } catch (Exception e) {
      String subject = "SFTPToS3Service Failed";
      notificationService.notify(subject, GeneralUtils.getStackTrace(e));
      throw new RuntimeException(subject, e);
    }
  }

  public void checkForCompletion(File newFile) throws InterruptedException {
    long fileSize;
    long lastModified;
    do {
      fileSize = newFile.length();
      lastModified = newFile.lastModified();
      logger.info(String.format("File '%s' => current size:%d, last modified time:%s",
        newFile.toString(), fileSize, lastModified));
      Thread.sleep(1000);
    } while (fileSize != newFile.length() || lastModified != newFile.lastModified());
  }
}
