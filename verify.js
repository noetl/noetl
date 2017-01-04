var User = require('./models/user');

var jwt = require('jsonwebtoken');
var config = require('./config.js');

exports.getToken = function(user){
  return jwt.sign(user, config.secretKey, {expiresIn: 86400 * 365});
};
exports.verifyOrdinaryUser = function(req, res, next){

  var token = req.headers['x-access-token'];

  if(token){
    jwt.verify(token, config.secretKey, function(err, decoded){
      if(err){
        var err = new Error();
        err.status = 401;
        err.message = 'Unauthorized';
        return next(err);
      }
      else{
        req.decoded = decoded;
        if(req.decoded.status === true){
          var err = new Error();
          err.status = 403;
          err.message = 'Forbidden';
          return next(err);
        }
        next();
      }
    });
  }
  else{
    var err = new Error();
    err.status = 403;
    err.message = 'Forbidden';
    return next(err);
  }

};
exports.verifyAdmin = function(req, res, next){
  if(!req.decoded){
    var err = new Error();
    err.status = 401;
    err.message = 'Unauthorized';
    return next(err);
  }
  else{
    if(req.decoded.accessLevel != 'admin'){
      var err = new Error();
      err.status = 403;
      err.message = 'Forbidden';
      return next(err);
    }
    else{next();}
  }
};