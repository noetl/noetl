'use strict';
  angular.module('noetlApp')

    .controller('GlobalController', function ($scope, Users, $state, $rootScope, ngDialog, $localStorage, AuthFactory, $timeout, $location, $mdMedia) {


        $scope.errorHandler = function(err){
            if(err.status === 401){
                $scope.logOut();
                $location.path('/');
            }
            else if(err.status === 403){
                $location.path('/');
            }
            else if(err.status === 500){
                $location.path('/');
            }
            else{
                $scope.logOut();
                $location.path('/');
            }
        };

    
        if(AuthFactory.isAuthenticated()){
            $scope.loggedIn = true;
            Users.return(function(res){
                $scope.user = res;
                if(res.accessLevel === 'admin'){
                    $scope.isAdmin = true;
                }
                else {
                    $scope.isAdmin = false;
                }
                if(res.status[0].blocked){
                    $scope.isBlocked = true;
                }
                else {$scope.isBlocked = false;}
    
            }, function(err){
                if(err.status === 403){
                    $scope.isBlocked = true;
                }
                else{
                    $scope.loggedIn = false;
                }
            });
        }
        else {$scope.loggedIn = false;}
    

        $scope.auth = function (action) {
    
            if(action === 'login'){
                ngDialog.open({
                    template: 'views/login.html',
                    scope: $scope,
                    className: 'ngdialog-theme-default',
                    controller:"LoginController",
                    showClose: false
                });
            }
            else if(action === 'register'){
                ngDialog.open({
                    template: 'views/register.html',
                    scope: $scope,
                    className: 'ngdialog-theme-default',
                    controller:"RegisterController",
                    showClose: false
                });
            }
            else{}
    
    
    
        };
    
        $scope.logOut = function() {
            AuthFactory.logout();
            $scope.loggedIn = false;
        };
    
        $rootScope.$on('login:Successful', function () {
            $scope.loggedIn = AuthFactory.isAuthenticated();
    
            Users.return(function(res){
                $scope.user = res;
                if(res.accessLevel === 'admin'){
                    $scope.isAdmin = true;
                }
                else {
                    $scope.isAdmin = false;
                }
                if(res.status[0].blocked){
                    $scope.isBlocked = true;
                }
                else {$scope.isBlocked = false;}
    
            }, function(err){
                if(err.status === 403){
                    $scope.isBlocked = true;
                }
                else{
                    $scope.loggedIn = false;
                }
            });
    
        });
    
        $rootScope.$on('registration:Successful', function () {
            $scope.loggedIn = AuthFactory.isAuthenticated();
            Users.return(function(res){
                $scope.user = res;
                if(res.accessLevel === 'admin'){
                    $scope.isAdmin = true;
                }
                else {
                    $scope.isAdmin = false;
                }
                if(res.status[0].blocked){
                    $scope.isBlocked = true;
                }
                else {$scope.isBlocked = false;}
    
            }, function(err){
                if(err.status === 403){
                    $scope.isBlocked = true;
                }
                else{
                    $scope.loggedIn = false;
                }
            });
        });


})
    .controller('IndexController', function ($scope, Comments, Universal, Subscriptions, Rating, $timeout){


    })



    .controller('DashboardController', function (AuthFactory, $location, $scope){
        if(AuthFactory.isAuthenticated()){}
        else{$location.path('/');}
    })

    



    .controller('CabinetController', function (AuthFactory, $scope, Projects, Refbacks, $location, $timeout){

        if(AuthFactory.isAuthenticated()){}
        else{$location.path('/');}

    })
      


    .controller('ProjectsController', function ($scope, Universal, $timeout){

        if(AuthFactory.isAuthenticated()){}
        else{$location.path('/');}

    })
    .controller('ProjectDetailsController', function (AuthFactory, Comments, Universal, $timeout, $rootScope, $scope, Rating, Project){

        if(AuthFactory.isAuthenticated()){}
        else{$location.path('/');}

      })





    .controller('LoginController', function ($scope, ngDialog, $localStorage, AuthFactory) {

          $scope.loginData = $localStorage.getObject('userinfo','{}');

        $scope.turnOff = function () {
            ngDialog.close();
        }

          $scope.doLogin = function() {
              if($scope.rememberMe)
                  $localStorage.storeObject('userinfo',$scope.loginData);

              AuthFactory.login($scope.loginData);
              ngDialog.close();


          };



      })
    .controller('RegisterController', function ($scope, ngDialog, $localStorage, AuthFactory) {

        $scope.turnOff = function () {
            ngDialog.close();
        }
          $scope.register={};
          $scope.loginData={};

          $scope.doRegister = function() {
              AuthFactory.register($scope.registration);
              ngDialog.close();
          };
      });