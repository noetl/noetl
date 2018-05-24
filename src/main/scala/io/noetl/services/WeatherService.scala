package io.noetl.services

import akka.actor.ActorSystem
import akka.event.Logging
import akka.http.scaladsl.model.Uri.Query
import akka.http.scaladsl.model._
import akka.stream.ActorMaterializer
import cats.data.EitherT
import cats.syntax.either._
import io.circe.parser._
import io.noetl.model.{Error, WeatherInfo}
import monix.eval.Task
import scala.language.higherKinds

trait WeatherService[F[_]] {
  def fetchWeather(city: String): F[Either[Error, WeatherInfo]]
}

final class WeatherServiceInterpreter(implicit system: ActorSystem, mat: ActorMaterializer)
    extends WeatherService[Task] {

  import io.noetl.config.AppConfig.config
  implicit val log = Logging(system, this.getClass)

  override def fetchWeather(city: String): Task[Either[Error, WeatherInfo]] = {
    def createOpenWeatherMapRequest(city: String): HttpRequest = {
      val params = Seq(
        "q" -> city,
        "mode" -> "json",
        "units" -> "metric",
        "appid" -> config.endpoints.weather.appid
      )
      HttpRequest(
        method = HttpMethods.GET,
        uri = Uri(config.endpoints.weather.url).withQuery(Query(params: _*))
      )
    }

    val result = for {
      data <- EitherT(fetchResource(createOpenWeatherMapRequest(city)))
      weather <- EitherT(Task.now(decode[WeatherInfo](data.utf8String).leftMap(e => Error(e.getMessage))))
    } yield {
      weather
    }

    result.value
  }
}
