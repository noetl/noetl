var express = require('express'),
    helmet = require('helmet'),
    app = express(),
    morgan = require('morgan'),
    bodyParser = require('body-parser'),
    mongoose = require('mongoose'),
    passport = require('passport'),
    authenticate = require('./authenticate'),
    config = require('./config'),
    Verify = require('./verify'),
    User = require('./models/user');



var passport = require('passport');
var authenticate = require('./authenticate');


mongoose.Promise = global.Promise;
mongoose.connect(config.mongoUrl);
var db = mongoose.connection;
db.on('error', console.error.bind(console, 'connection error:'));
db.once('open', function () {
  console.log("Connected correctly to server");
});

var indexRouter = require('./routes/indexRouter');

// Security
app.use(helmet());

// Secure traffic only
// app.all('*', function(req, res, next){
//   if(req.secure){return next();}
//   res.redirect('https://' + req.hostname + ':' + app.get('secPort') + req.url);
// });



// passport config
app.use(passport.initialize());

app.use(express.static(__dirname + '/public'));
app.use('/', indexRouter);

app.all('/*', function(req, res, next) {
  // Just send the index.html for other files to support HTML5Mode
  res.sendFile('/public/index.html', { root: __dirname });
});

app.use(morgan('dev'));
app.use(bodyParser.json());




app.use(function(err, req, res, next) {
  console.error(err);
  res.status(err.status).send(err.message);
});


module.exports = app;