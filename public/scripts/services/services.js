'use strict';

angular.module('noetlApp')
    .factory("baseURL", function ($location) {
        return $location.$$protocol + '://' + $location.$$host + ':' +$location.$$port + '/';
    })
    .factory('Universal', function($resource, baseURL) {
        return $resource(baseURL + 'universal/:id', {"id": "@id"}, {
            'findPosts': {
                method: "GET",
                url: baseURL + 'universal/all-posts',
                isArray: true
            },
            'findProjects': {
                method: "GET",
                url: baseURL + 'universal/all-projects',
                isArray: true
            },
            'findOne': {
                method: 'GET',
                url: baseURL + 'universal/:id',
                id: '@id'
            },
            'create':{
                method: "POST",
                url: baseURL + 'universal/create',
                isArray: false
            },
            'delete':{
                method: "POST",
                url: baseURL + 'universal/delete',
                isArray: false
            },
            'update':{
                method: "POST",
                url: baseURL + 'universal/update',
                isArray: false
            },
            'like':{
                method: "POST",
                url: baseURL + 'universal/like',
                isArray: false
            }
        });
    })
    .factory('Users', function($resource, baseURL) {
        return $resource(baseURL + 'users/:id', {}, {
            'find': {
                method: "GET",
                url: baseURL + 'users/all',
                isArray: true
            },
            'findOne': {
                method: 'GET',
                url: baseURL + 'users/:id',
                id: '@id'
            },
            'return': {
                method: 'GET',
                url: baseURL + 'users/return'
            },
            'block':{
                method: "POST",
                url: baseURL + 'users/block'
            },
            'check':{
                method: "POST",
                url: baseURL + 'users/email'
            },
            'delete':{
                method: "POST",
                url: baseURL + 'users/delete'
            },
            'save':{
                method: "POST",
                url: baseURL + 'users/save'
            }

        });
    })
    .factory('$localStorage', ['$window', function ($window) {
        return {
            store: function (key, value) {
                $window.localStorage[key] = value;
            },
            get: function (key, defaultValue) {
                return $window.localStorage[key] || defaultValue;
            },
            remove: function (key) {
                $window.localStorage.removeItem(key);
            },
            storeObject: function (key, value) {
                $window.localStorage[key] = JSON.stringify(value);
            },
            getObject: function (key, defaultValue) {
                return JSON.parse($window.localStorage[key] || defaultValue);
            }
        }
    }])
    .factory('AuthFactory', function($resource, $http, $q, $localStorage, $rootScope, $window, baseURL, ngDialog){

        var authFac = {};
        var TOKEN_KEY = 'Token';
        var isAuthenticated = false;
        var username = '';
        var authToken = undefined;
        var userStatus = '';

        function loadUserCredentials() {
            var credentials = $localStorage.getObject(TOKEN_KEY,'{}');
            if (credentials.username != undefined) {
                useCredentials(credentials);
            }
        }
        function storeUserCredentials(credentials) {
            $localStorage.storeObject(TOKEN_KEY, credentials);
            useCredentials(credentials);

        }
        function useCredentials(credentials) {
            isAuthenticated = true;
            username = credentials.username;
            authToken = credentials.token;


            // Set the token as header for your requests!
             $http.defaults.headers.common['x-access-token'] = authToken;



            // console.log($http.defaults.headers.common['x-access-token']);
        }
        function destroyUserCredentials() {
            authToken = undefined;
            username = '';
            isAuthenticated = false;
            $http.defaults.headers.common['x-access-token'] = authToken;
            $localStorage.remove(TOKEN_KEY);
        }

        authFac.login = function(loginData) {

            $resource("/login")
                .save(loginData,
                    function(response) {
                        storeUserCredentials({username:loginData.username, token: response.token});
                        $rootScope.$broadcast('login:Successful');
                    },
                    function(response){
                        isAuthenticated = false;

                        var message = '<h3 style="margin:15px;">Введены неверные данные!</h3>';
                        ngDialog.openConfirm({ template: message, plain: 'true'});
                    }
                );

        };

        authFac.logout = function() {

            $resource("/logout").get(function(response){});
            destroyUserCredentials();
        };


        authFac.register = function(registerData) {

            $resource("/register")
                .save(registerData,
                    function(response) {
                        authFac.login({username:registerData.username, password:registerData.password});
                        if (registerData.rememberMe) {
                            $localStorage.storeObject('userinfo',
                                {username:registerData.username, password:registerData.password});
                        }

                        $rootScope.$broadcast('registration:Successful');
                    },
                    function(response){

                        var message = '<h3 style="margin:15px;">Регистрация отклонена</h3>';

                        ngDialog.openConfirm({ template: message, plain: 'true'});

                    }
                );
        };


        authFac.isAuthenticated = function() {
            return isAuthenticated;
        };

        

        loadUserCredentials();

        return authFac;
    });