package io.noetl.api

import cats.Monad
import cats.data.EitherT
import io.circe.{Decoder, Encoder}
import io.circe.generic.semiauto.{deriveDecoder, deriveEncoder}
import io.noetl.model.{CountryInfo, WeatherInfo}
import io.noetl.services.{CountryService, WeatherService}
import scala.language.higherKinds

class Api {
  import Api._

  def program[F[_]: Monad](city: String)(
      implicit W: WeatherService[F],
      C: CountryService[F]
  ): F[Either[io.noetl.model.Error, Info]] = {

    import W._, C._

    val result = for {
      weather <- EitherT(fetchWeather(city))
      country <- EitherT(fetchCountry(city))
    } yield Info(city, Some(country), Some(weather))

    result.value
  }
}

object Api {

  final case class Info(city: String, countryInfo: Option[CountryInfo], weatherInfo: Option[WeatherInfo])
  object Info {
    implicit val decoder: Decoder[Info] = deriveDecoder
    implicit val encoder: Encoder[Info] = deriveEncoder
  }
}
