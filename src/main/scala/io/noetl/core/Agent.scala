package io.noetl.core

import io.noetl.store._
import scala.util.Try


object Agent  {

  def main (args: Array[String]): Unit = {

    // if (args.isEmpty) throw new IllegalArgumentException(s"Path for config file is not provided")

    val configPath = Try(args(0)).getOrElse("")

    val config =  actionsExists(getConfig(configPath))

    val actionFlow = ActionFlow(config)

    println(actionFlow.toString)

  }

}
