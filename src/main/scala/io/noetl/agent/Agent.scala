package io.noetl.agent

import scala.util.Try

object Agent {

  def main(args: Array[String]): Unit = {

    if (args.isEmpty)
      throw new IllegalArgumentException(
        s"Path for config file is not provided")

    val configPath = Try(args(0)).getOrElse(
      "src/main/resources/conf/tnotb-akuksin-xchg-rate-20180601.conf")

    val workflowConfig = validateWorkflowConfig(configPath)

    // println(workflowConfig)

    val start = workflowConfig.start.get.subscribers.get.map(actionKey =>  workflowConfig.actions(actionKey))

    start.foreach(x => x.runAction)

    println(start.getClass.getName)


  } // end of main
}
