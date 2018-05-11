package io.noetl.core

import com.typesafe.config._
import scala.util.Try
// http://www.scala-lang.org/api/2.12.0-M5/scala/collection/JavaConversions$.html - deprecated since 2.12. Use if need to downgrade to 2.8
import scala.collection.JavaConverters._
import ActionType._

// some examples https://marcinkubala.wordpress.com/2013/10/09/typesafe-config-hocon/


trait ActionConfig {
  val name: String
  def actionType(config: Config): ActionType = ActionConfig.getActionType(config)
  def displayName(config: Config): String = config.getString("displayName")
  def description(config: Config): String = config.getString("description")
  def next(config: Config): List[String] = config.getStringList("next").asScala.toList
  def actionRun(config: Config): ActionRun = ActionRun(Try(Some(config.getConfig("run"))).getOrElse(None))

  def printCmd(cmd: String): Unit = println(cmd)
  def printCmd(): Unit = println(this.toString)
  def execSuccess(): Int = 0
  def execFailed(): Int = -1
}
// https://alvinalexander.com/scala/how-to-create-factory-method-in-scala-apply-object-trait
object ActionConfig {

  def getActionType(config: Config): ActionType = {
    ActionType(Try(config.getString("type")).getOrElse("action"))
  }
  //https://developer.lightbend.com/docs/alpakka/current/

  private case class Action(name: String, config: Config) extends ActionConfig {
    def exec () = "aa"
  }
  private case class Start(name: String, config: Config) extends ActionConfig
  private case class End(name: String, config: Config) extends ActionConfig
  private case class Fork(name: String, config: Config) extends ActionConfig
  private case class Join(name: String, config: Config) extends ActionConfig
  private case class Webservice(name: String, config: Config) extends ActionConfig
  private case class Shell(name: String, config: Config) extends ActionConfig
  private case class Jdbc(name: String, config: Config) extends ActionConfig
  private case class Ssh(name: String, config: Config) extends ActionConfig
  private case class Scp(name: String, config: Config) extends ActionConfig

  def apply(actionName: String, config: Config): ActionConfig = config match {
      // https://alvinalexander.com/scala/how-to-use-if-then-expressions-guards-in-case-statements-scala
    case action if this.getActionType(action) == ACTION => Action(actionName, config)
    case start if this.getActionType(start) == START => Start(actionName, config)
    case end if this.getActionType(end) == END => End(actionName, config)
    case fork if this.getActionType(fork) == FORK => Fork(actionName, config)
    case join if this.getActionType(join) == JOIN => Join(actionName, config)
    case webservice if this.getActionType(webservice) == WEBSERVICE => Webservice(actionName, config)
    case shell if this.getActionType(shell) == SHELL => Shell(actionName, config)
    case jdbc if this.getActionType(jdbc) == JDBC => Jdbc(actionName, config)
    case ssh if this.getActionType(ssh) == SSH => Ssh(actionName, config)
    case scp if this.getActionType(scp) == SCP => Scp(actionName, config)
    case _ => throw new IllegalArgumentException(actionName)

  }
}

case class ActionRun(config: Config = ConfigFactory.empty())

object ActionRun {
  def apply (actionRun: Option[Config] ): ActionRun = actionRun match {
    case x: Some[Config] => new ActionRun(actionRun.get)
    case _ =>   new ActionRun()
  }
}

case class ActionRunExit(code: String = "0", message: String = "" )






