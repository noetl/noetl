import akka.actor.ActorSystem
import akka.event.LoggingAdapter
import akka.http.scaladsl.Http
import akka.http.scaladsl.model.{HttpRequest, StatusCodes}
import akka.stream.ActorMaterializer
import akka.stream.scaladsl.Sink
import akka.util.ByteString
import io.noetl.model.Error
import monix.eval.Task

import scala.concurrent.duration._
import scala.util.{Failure, Success}

package object services {

  private def retryBackoff[A](source: Task[A], maxRetries: Int, firstDelay: FiniteDuration)(
      implicit log: LoggingAdapter): Task[A] = {

    source.onErrorHandleWith {
      case ex: Exception =>
        if (maxRetries > 0) {
          log.info(s"$ex: Retrying (${maxRetries - 1})... ")
          retryBackoff(source, maxRetries - 1, firstDelay * 2).delayExecution(firstDelay)
        } else {
          Task.raiseError(ex)
        }
    }
  }

  def fetchResource(
      request: HttpRequest
  )(implicit system: ActorSystem, mat: ActorMaterializer, log: LoggingAdapter): Task[Either[Error, ByteString]] = {

    val task = Task.deferFuture(Http().singleRequest(request))
    val taskWithExponentialBackoff = retryBackoff(task, 5, 2.seconds)
    taskWithExponentialBackoff.materialize.flatMap {
      case Success(response) =>
        if (response.status == StatusCodes.OK) {
          Task.fromFuture {
            response.entity.dataBytes
              .runWith(Sink.fold(Left(Error("")): Either[Error, ByteString]) { (acc, b) =>
                acc match {
                  case Left(_)  => Right(b)
                  case Right(a) => Right(a ++ b)
                }
              })
          }
        } else {
          Task.now(Left(Error(response.toString)))
        }

      case Failure(ex) =>
        Task.now(Left(Error(s"Err: $ex")))
    }
  }
}
