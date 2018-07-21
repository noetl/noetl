package io.noetl.agent

case class
RequirementForStart(
                     actionKey: String,
                     status: String,
                     description: Option[String]
                   )

sealed trait
ActionConf {
  val displayName: String
  val requirementsForStart: List[RequirementForStart]
  val tryStart: List[String]
  val description: Option[String]
}

case class
ShellConf(
           displayName: String,
           requirementsForStart: List[RequirementForStart],
           tryStart: List[String],
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
