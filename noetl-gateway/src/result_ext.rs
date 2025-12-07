use tracing::*;

pub trait ResultExt<T, E, S>
where
    S: ToString,
{
    fn log(self, context: S) -> Result<T, E>;
}

impl<T, E: std::fmt::Display, S: ToString> ResultExt<T, E, S> for Result<T, E> {
    #[track_caller]
    fn log(self, context: S) -> Result<T, E> {
        if self.is_err() {
            let caller_location = std::panic::Location::caller();
            let caller_line_file = caller_location.file();
            let caller_line_number = caller_location.line();
            error!(target: "normal",
                err=%self.as_ref().err().unwrap(),
                file=%format!(" {caller_line_file}:{caller_line_number}"),
                "{context}",
                context=context.to_string());

            // error!(target: "normal", "{caller_line_file}:{caller_line_number} {context}. Err {err}",
            //     context=context.to_string(), err=self.as_ref().err().unwrap());
        }
        self
    }
}
