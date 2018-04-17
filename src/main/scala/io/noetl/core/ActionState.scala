package io.noetl.core

object ActionState {
    sealed trait ActionState
    case object PENDING extends ActionState
    case object STARTED extends ActionState
    case object RUNNING extends ActionState
    case object PAUSED extends ActionState
    case object FAILED extends ActionState
    case object FINISHED extends ActionState
    case object UNKNOWN extends ActionState

    val elements = Set (PENDING, STARTED, RUNNING, PAUSED, FAILED, FINISHED, UNKNOWN)

    def apply (value: String) =
      if (PENDING.toString == value.toUpperCase) PENDING
      else if (STARTED.toString == value.toUpperCase) STARTED
      else if (RUNNING.toString == value.toUpperCase) RUNNING
      else if (PAUSED.toString == value.toUpperCase) PAUSED
      else if (FAILED.toString == value.toUpperCase) FAILED
      else if (FINISHED.toString == value.toUpperCase) FINISHED
      else if (UNKNOWN.toString == value.toUpperCase) UNKNOWN
      else throw new IllegalArgumentException
}
