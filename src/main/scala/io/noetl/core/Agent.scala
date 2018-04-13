package io.noetl.core

import java.io.File
import com.typesafe.config._
import scala.util.Try


object Agent  {

  def main (args: Array[String]): Unit = {

    val fs = File.separator

    val configPath = Try(args(0)).getOrElse("/Users/refugee/projects/noetl/noetl/src/main/resources/conf/job1.conf")

    val configFactory = ConfigFactory.parseFile(new File(configPath))

    val config = ConfigFactory.load(configFactory)

    val hasActions  = Try {
      config.hasPath("actions")
    }.getOrElse(false)

    if (!hasActions)
      throw new IllegalArgumentException(s"config validation failed")
    else
      println(s"config validation passed")

    val actions = config.getObject("actions")

    println(actions)




  }




}
