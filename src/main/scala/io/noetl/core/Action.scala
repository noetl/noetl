package io.noetl.core

trait Action {
 val actionName: String
 val actionType: String
 val actionRun: ActionRun

}
