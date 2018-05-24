package io.noetl.services

import akka.actor.ActorSystem
import akka.event.Logging
import akka.http.scaladsl.model._
import akka.stream.ActorMaterializer
import cats.data.EitherT
import cats.syntax.either._
import io.circe.parser._
import io.noetl.model.{Error, CountryInfo}
import monix.eval.Task
import scala.language.higherKinds

trait CountryService[F[_]] {
  def fetchCountry(city: String): F[Either[Error, CountryInfo]]
}

final class CountryServiceInterpreter(implicit system: ActorSystem, mat: ActorMaterializer)
    extends CountryService[Task] {

  import io.noetl.config.AppConfig.config
  implicit val log = Logging(system, this.getClass)

  override def fetchCountry(city: String): Task[Either[Error, CountryInfo]] = {
    def createRestCountriesRequest(city: String): HttpRequest = {
      HttpRequest(
        method = HttpMethods.GET,
        uri = Uri(s"${config.endpoints.countries.url}/rest/v2/capital/$city"),
        entity = HttpEntity(ContentTypes.`application/json`, "")
      )
    }

    val result = for {
      data <- EitherT(fetchResource(createRestCountriesRequest(city)))
      countries <- EitherT(Task.now(decode[List[CountryInfo]](data.utf8String).leftMap(e => Error(e.getMessage))))
    } yield {
      countries.head
    }

    result.value
  }
}
