package io.noetl

package core {

  import scala.util.Try

  case class Url(hosts: Vector[String])

  case class Fun(name: Option[String], args: Vector[String])

  object Fun {
    def apply(name: Option[String], args: Vector[String]): Fun = (name,args) match
    {
      case _ => new Fun(Try(name).getOrElse(None),Try(args).getOrElse(Vector()))
    }
  }

  case class Run(
                  after: Option[String] = None,
                  state: Option[String] = None,
                  message: Option[String] = None,
                  next: Option[Vector[String]] = None,
                  fun: Option[Fun] = None
                )

  object Run {
    def apply(after: Option[String],state: Option[String],message: Option[String],next: Option[Vector[String]], fun: Option[Fun] ): Run = (after,state,message,next,fun) match
    {
      case (None,None,None,None,None) => new Run()
      case _ => new Run(Try(after).getOrElse(None),Try(state).getOrElse(None),Try(message).getOrElse(None),Try(next).getOrElse(None),Try(fun).getOrElse(None))
    }
  }

}

package object core {}