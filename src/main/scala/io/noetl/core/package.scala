package io.noetl

package core {

  import com.typesafe.config._
  import scala.util.Try
  import scala.collection.JavaConverters._



  case class NoetlDb (name: String, host: String, home: String, path: String, file: String, main: String)

  object NoetlDb {
    def apply(config: Config): NoetlDb = config match {
      case _ => new NoetlDb(
        name = config.getString("name"),
        host = config.getString("host"),
        home = config.getString("home"),
        path = config.getString("path"),
        file = config.getString("file") ,
        main = config.getString("main")
      )
    }
  }

  case class Url(hosts: Vector[String])

  case class ActionFun(name: String, args: List[String])

  object ActionFun {
    def apply(config: Config): ActionFun = config match
    {
      case _ => new ActionFun(config.getString("name"),config.getStringList("args").asScala.toList)
    }
  }

  case class ActionRun(
                  when: List[String] = List.empty[String],
                  after: List[String] = List.empty[String],
                  state: String = "pending",
                  message: String = "waitning for start",
                  next: List[String] = List.empty[String],
                  fun: ActionFun
                )

  object ActionRun {
    def apply(config: Config): ActionRun = config match
    {
      case _ => new ActionRun(
        Try(config.getStringList("when").asScala.toList).getOrElse(List.empty[String]),
        Try(config.getStringList("after").asScala.toList).getOrElse(List.empty[String]),
        Try(config.getString("state")).getOrElse("pending"),
        Try(config.getString("message")).getOrElse("waitning for start"),
        Try(config.getStringList("next").asScala.toList).getOrElse(List.empty[String]),
        ActionFun(config.getConfig("fun"))
        )
    }
  }

}

package object core {}