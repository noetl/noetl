package io.noetl

import akka.actor.ActorSystem
import akka.event.Logging
import akka.http.scaladsl.model.StatusCodes
import akka.stream.ActorMaterializer
import io.noetl.api.Api
import io.noetl.services.{CountryServiceInterpreter, WeatherServiceInterpreter}
import monix.eval.Task
import monix.execution.Scheduler

object Programs {
  implicit val clientSystem: ActorSystem = ActorSystem("client")
  implicit val clientMat: ActorMaterializer = ActorMaterializer()
  private val log = Logging(clientSystem, this.getClass)

  implicit val weatherService = new WeatherServiceInterpreter
  implicit val countryService = new CountryServiceInterpreter

  implicit val blockingOpsScheduler = Scheduler.io()

  val api = new Api()
  val programT = (city: String) =>
    api
      .program[Task](city)
      .runAsync
      .map {
        case Right(d) =>
          StatusCodes.OK -> d.asJson
        case Left(err) =>
          println(err.msg.asJson)
          StatusCodes.BadRequest -> err.asJson
    }
}
