package io.noetl.core

import com.typesafe.config._

import scala.util.Try
// http://www.scala-lang.org/api/2.12.0-M5/scala/collection/JavaConversions$.html - deprecated since 2.12. Use if need to downgrade to 2.8
import scala.collection.JavaConverters._
import ActionType._
import ActionState._

// some examples https://marcinkubala.wordpress.com/2013/10/09/typesafe-config-hocon/


case class ActionRun(config: Config = ConfigFactory.empty())

object ActionRun {
  def apply (actionRun: Option[Config] ): ActionRun = actionRun match {
    case x: Some[Config] => new ActionRun(actionRun.get)
    case _ =>   new ActionRun()
  }
}

case class ActionConfig (
 name: String,
 actionType: ActionType,
 displayName: String,
 description: String,
 next: List[String],
 actionRun: ActionRun
                  )


object ActionConfig {
  def apply(actionName: String, config: Config): ActionConfig = config match {
    case _ => new ActionConfig(
      name = actionName,
      actionType = ActionType(Try(config.getString("type")).getOrElse("action")),
      displayName = config.getString("displayName"),
      description = config.getString("description"),
      next =  config.getStringList("next").asScala.toList,
      actionRun = ActionRun(Try(Some(config.getConfig("run"))).getOrElse(None))
    )
  }
}



case class ActionRunExit(code: String = "0", message: String = "" )






