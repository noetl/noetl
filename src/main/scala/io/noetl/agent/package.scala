package io.noetl

import scala.util.Try

package agent {

  sealed trait ActionType
  case object ACTION extends ActionType
  case object START extends ActionType
  case object END extends ActionType
  case object FORK extends ActionType
  case object JOIN extends ActionType
  case object WEBSERVICE extends ActionType
  case object SHELL extends ActionType
  case object JDBC extends ActionType
  case object SSH extends ActionType
  case object SCP extends ActionType

}

package object agent {
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
