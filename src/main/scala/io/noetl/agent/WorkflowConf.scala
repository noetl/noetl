package io.noetl.agent

case class
Dependency(
                     actionKey: String,
                     status: String,
                     description: Option[String]
                   )

sealed trait
ActionConf {
  val displayName: String
  val runDependencies: List[Dependency]
  val subscribers: List[String]
  val description: Option[String]
}

case class
ShellConf(
           displayName: String,
           runDependencies: List[Dependency],
           subscribers: List[String],
           variables: Option[Map[String, String]],
           shellScript: List[String],
           description: Option[String],
         ) extends ActionConf

case class
WorkflowConf(
              name: String,
              start: List[String],
              displayName: Option[String],
              description: Option[String],
              variables: Option[Map[String, String]],
              input: Option[Map[String, String]],
              actions: Map[String, ActionConf]
            )
