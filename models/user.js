var mongoose = require('mongoose');
var Schema = mongoose.Schema;
var passportLocalMongoose = require('passport-local-mongoose');


var User = new Schema({
  username: {
    type: String,
    required: true,
    unique: true
  },
  password: {
    type: String
  },
  email: {
    type: String,
    required: true,
    unique: true
  },
  status: [{
    email: Boolean,
    blocked: Boolean
  }],
  accessLevel: {
    type: String,
    default: 'user'
  }
});



User.plugin(passportLocalMongoose);

module.exports = mongoose.model('User', User);