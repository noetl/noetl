package io.noetl.core
// https://stackoverflow.com/questions/1898932/case-objects-vs-enumerations-in-scala?utm_medium=organic&utm_source=google_rich_qa&utm_campaign=google_rich_qa
object ActionType {
    sealed trait ActionType
    case object CONFIG extends ActionType
    case object ACTION extends ActionType

    val elements = Set ( CONFIG, ACTION)

    def apply (value: String) =
        if (ACTION.toString == value.toUpperCase) ACTION
        else if (CONFIG.toString == value.toUpperCase) CONFIG
        else throw new IllegalArgumentException
}
