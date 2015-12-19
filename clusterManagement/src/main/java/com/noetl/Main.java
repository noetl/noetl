package com.noetl;

import com.beust.jcommander.JCommander;
import com.beust.jcommander.Parameter;
import com.beust.jcommander.ParameterException;
import com.beust.jcommander.converters.FileConverter;
import com.noetl.automation.services.ClusterGenerationService;
import com.noetl.automation.services.ClusterTerminationService;
import com.noetl.automation.services.SFTPToS3Service;
import com.noetl.parsers.JsonParser;
import com.noetl.pojos.AutomationConf;
import com.noetl.utils.GeneralUtils;
import org.apache.log4j.Logger;

import java.io.File;

public class Main {
  private static Logger logger;
  @Parameter(names = {"--conf"},
    description = "Set the path for configuration file",
    required = true,
    converter = FileConverter.class)
  private File conf = null;

  @Parameter(names = {"--sftpToS3"},
    description = "This service monitors a SFTP location specified by monitorConf.sftpConf.source. Once it detects any new file or folder, the new file or folder will be uploaded to two S3 locations. One is configured by the monitorConf.s3Conf.backup; this location should keep all historical data files. The other one is specified by monitorConf.s3Conf.stage; this location should stage all files for the next pipeline. After files have been uploaded to S3, they will be moved to a backup location specified by monitorConf.sftpConf.destination. It creates a time stamped folder in the format of YYYY.MM.DD at the destination and move the file there.")
  private boolean sftpToS3 = false;

  @Parameter(names = {"--clusterGeneration"},
    description = "This service monitors a S3 location(specified by monitorConf.s3Conf.stage) and starts the cluster for pipeline once everything is ready('Everything' is specified in monitorConf.expectedFiles).\n" +
      "\tThis service will create a ClusterStarted file in the root path(specified in rootPath in configuration file) once the start request has been sent to AWS. The file name contains the job flow id after @. And the program will write to this file the information of the master DNS name and all files used for pipeline after the cluster has been spin up successfully.\n" +
      "\tThis service will not start the cluster if it sees the existence of the ClusterStarted file. So you need to make sure to remove this file in order to use this service.\n")
  private boolean clusterGeneration = false;

  @Parameter(names = {"--clusterTermination"},
    description = "This service shuts down the cluster as requested.\n" +
      "\tThe cluster id it will shut down is specified by the ClusterStarted file. In detail, the code scans the root path(specified in rootPath in configuration file), looks for the ClusterStarted file, parses the job flow id out from the file name(the part after @) and shut down that cluster. After the cluster gets shut down successfully, the ClusterStarted file will be removed.")
  private boolean clusterTermination = false;

  @Parameter(names = {"-h", "-?", "-help", "--help"}, help = true, hidden = true)
  private boolean help = false;

  public static void main(String[] args) {
    Main main = new Main();
    JCommander jCommander = new JCommander(main);
    jCommander.setProgramName(main.getClass().getName());
    try {
      jCommander.parse(args);
      if (main.help) {
        jCommander.usage();
        System.exit(0);
      }

      AutomationConf automationConf = JsonParser.getMapper().readValue(main.conf, AutomationConf.class);
      System.setProperty("logfile.name", automationConf.getLogFile());

      logger = Logger.getLogger(Main.class);
      if (main.sftpToS3) {
        logger.info("Starting the service to monitor SFTP source");
        SFTPToS3Service service = new SFTPToS3Service(automationConf);
        service.startService();
      } else if (main.clusterGeneration) {
        logger.info("Starting the service to monitor S3 stage and spin up cluster once ready");
        ClusterGenerationService service = new ClusterGenerationService(automationConf);
        service.startService();
      } else if (main.clusterTermination) {
        logger.info("Starting the service to shut down clusters");
        ClusterTerminationService service = new ClusterTerminationService(automationConf);
        service.startService();
      } else
        logger.info("Please specify a job you want to do." + System.lineSeparator() + "Current options are: --sftpToS3, --clusterGeneration, --terminateCluster");
    }
    //TODO:Extract the notification service from base service and move it here.
    //Send error email when seeing an exception rather than in every catch block
    catch (ParameterException e) {
      String message = "Error parsing your arguments, please check the usage. " + e.getMessage();
      if (logger != null)
        logger.error(message);
      else
        System.out.println(message);
      jCommander.usage();
      System.exit(1);
    } catch (Exception e) {
      String errorMessage = GeneralUtils.getStackTrace(e);
      if (logger != null)
        logger.error(errorMessage);
      else
        System.out.println(errorMessage);
      System.exit(1);
    }
  }
}
