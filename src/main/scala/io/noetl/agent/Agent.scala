package io.noetl.agent

import scala.io.StdIn
import scala.util.Try

object Agent {

  def main(args: Array[String]): Unit = {

    // if (args.isEmpty)
    //  throw new IllegalArgumentException(
    //    s"Path for config file is not provided")

    val configPath = Try(args(0)).getOrElse(
      "src/main/resources/conf/tnotb-akuksin-xchg-rate-20180601_no_coments.conf")

    val workflowConfig = validateWorkflowConfig(configPath)

    ActionFlow(workflowConfig).runFlow

    println(s"Press RETURN to stop...")
    StdIn.readLine()
  } // end of main
}
