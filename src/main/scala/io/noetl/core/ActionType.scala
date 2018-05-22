package io.noetl.core
// https://stackoverflow.com/questions/1898932/case-objects-vs-enumerations-in-scala?utm_medium=organic&utm_source=google_rich_qa&utm_campaign=google_rich_qa
object ActionType {
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

  val elements =
    Set(ACTION, START, END, FORK, JOIN, WEBSERVICE, SHELL, JDBC, SSH, SCP)

  def apply(value: String) = {
    // println("ActionType value", value)
    if (ACTION.toString == value.toUpperCase) ACTION
    else if (START.toString == value.toUpperCase) START
    else if (END.toString == value.toUpperCase) END
    else if (FORK.toString == value.toUpperCase) FORK
    else if (JOIN.toString == value.toUpperCase) JOIN
    else if (WEBSERVICE.toString == value.toUpperCase) WEBSERVICE
    else if (SHELL.toString == value.toUpperCase) SHELL
    else if (JDBC.toString == value.toUpperCase) JDBC
    else if (SSH.toString == value.toUpperCase) SSH
    else if (SCP.toString == value.toUpperCase) SCP
    else throw new IllegalArgumentException
  }
}
