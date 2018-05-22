package io.noetl.util

import org.apache.http.HttpResponse
import org.apache.http.client.methods.HttpUriRequest
import org.apache.http.concurrent.FutureCallback
import org.apache.http.impl.nio.client.{
  CloseableHttpAsyncClient,
  HttpAsyncClients
}
import scala.concurrent.{CancellationException, Promise}
import scala.util.Success

class HttpClientHandler(hc: CloseableHttpAsyncClient) {

  def execute(rq: HttpUriRequest) = {
    val p = Promise[HttpResponse]
    hc.execute(
      rq,
      new FutureCallback[HttpResponse] {
        def cancelled = p.failure(new CancellationException("cancelled"))
        def completed(r: HttpResponse) = p.complete(Success(r))
        def failed(ex: Exception) = p.failure(ex)
      }
    )
    p.future
  }

  def start = { hc.start; this }

  def close() = hc.close
}

object HttpClientHandler {
  def apply(hc: CloseableHttpAsyncClient) = new HttpClientHandler(hc)
  def apply() = new HttpClientHandler(HttpAsyncClients.createDefault)
}
