var express = require('express');
var indexRouter = express.Router();
var passport = require('passport');
var bodyParser = require('body-parser');
var mongoose = require('mongoose');
var async = require('async');



// Models
var User = require('../models/user'),
    Universal = require('../models/universal');

// Verification
var Verify = require('../verify');

indexRouter.use(bodyParser.json());



// Auth
indexRouter.route('/register').post(function (req, res, next){
    User.register(new User({
        username: req.body.username,
        email: req.body.email,
        invested: req.body.invested,
        refback: req.body.refback,
        accessLevel: req.body.accessLevel,
        status: [{"blocked": false, "email": false}]}), req.body.password,  function(err, user){
        if(err){
            var err = new Error();
            err.status = 500;
            err.message = 'Internal Server Error';
            return next(err);
        }
        passport.authenticate('local')(req, res, function(){
            return res.status(200).json(user);
        });
    });
});
indexRouter.route('/login').post(function (req, res, next){
        passport.authenticate('local', function(err, user, info){
            if(err){return next(err);}

            if(!user){
                var err = new Error();
                err.status = 401;
                err.message = 'Unauthorized';
                return next(err);
            }

            req.logIn(user, function(err){
                if(err){return next(err);}

                var token = Verify.getToken({"username": user.username, "_id": user._id, "accessLevel": user.accessLevel, "salt": user.salt, "hash": user.hash, "status": user.status[0].blocked});


                User.findOne({'username': user.username}, 'username status accessLevel', function (err, userData) {
                    if (err) {return next(err)};
                    res.status(200).json({
                        status: 'Login successful!',
                        success: true,
                        token: token,
                        userData: userData
                    });
                    next();
                });


            });

        })(req, res, next);
    });
indexRouter.route('/logout').get(function (req, res, next){
        req.logout();
        res.status(200).send('OKs');
    });



indexRouter.route('/universal/:url')
    .get(function (req, res, next) {
        res.status(200).json({});
    })
    .post(Verify.verifyOrdinaryUser, Verify.verifyAdmin, function (req, res, next) {
        res.status(200).json({});
    });



module.exports = indexRouter;