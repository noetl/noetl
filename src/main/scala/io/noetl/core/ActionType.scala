package io.noetl.core
// https://stackoverflow.com/questions/1898932/case-objects-vs-enumerations-in-scala?utm_medium=organic&utm_source=google_rich_qa&utm_campaign=google_rich_qa
object ActionType {
    sealed trait ActionType
    case object WORKFLOW extends ActionType
    case object FORK extends ActionType
    case object JOIN extends ActionType
    case object ACTION extends ActionType

    val elements = Set (WORKFLOW, ACTION, FORK, JOIN)

    def apply (value: String) =
      if (WORKFLOW.toString == value.toUpperCase) WORKFLOW
      else if (ACTION.toString  == value.toUpperCase) ACTION
      else if (FORK.toString  == value.toUpperCase) FORK
      else if (JOIN.toString  == value.toUpperCase) JOIN
      else throw new IllegalArgumentException
}
