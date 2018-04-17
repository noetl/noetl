package io.noetl.core

import java.io.File
import com.typesafe.config._
import scala.util.Try


object Agent  {

  def main (args: Array[String]): Unit = {

    val fs = File.separator

    val configPath = Try(args(0)).getOrElse( new java.io.File(".").getCanonicalPath + s"${fs}src${fs}main${fs}resources${fs}conf${fs}job1.conf")

    val configFactory = ConfigFactory.parseFile(new File(configPath))

    val config = ConfigFactory.load(configFactory)

    val hasActions  = Try {
      config.hasPath(ACTIONS) && config.hasPath(NOETLDB)
    }.getOrElse(false)

    if (!hasActions)
      throw new IllegalArgumentException(s"config validation failed")
    else
      println(s"config validation passed")

    val actionFlow = ActionFlow(config)

    println(actionFlow.toString)

  }




}
