package io.noetl

import scala.util.Try

package object core {
  import com.typesafe.config._
  val WORKFLOW = "workflow"
  val ACTIONS = "actions"

  def runShell(args: List[String]): Unit = {}

  def configKeyExists(keyPath: String, config: Config): Config = {
    val hasActions = Try {
      config.hasPath(keyPath)
    }.getOrElse(false)

    if (!hasActions)
      throw new IllegalArgumentException(s"NoETL config validation failed")
    else {
      println(s"config validation passed")
      config
    }
  }

}
