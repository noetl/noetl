'use strict';

angular.module('noetlApp', ['ui.router', 'ui.router.title', 'ui.tinymce', 'ngDialog', 'ngResource', 'ngProgress', 'ngAnimate', 'ngSanitize', 'ngAria', 'ngMaterial', 'slick'])
  .config(function($stateProvider, $urlRouterProvider) {

    $stateProvider
    // route for the home page
      .state('app', {
        url:'/',
        views: {
          'header': {
            templateUrl : 'views/header.html',
            controller  : 'HeaderController'
          },
          'content': {
            templateUrl : 'views/home.html',
            controller  : 'IndexController'
          },
          'footer': {
            templateUrl : 'views/footer.html',
          }
        },
        resolve: {
          $title: function() { return 'NoETL'; }
        }
      });

    $urlRouterProvider.otherwise('/');
    
  })

   .run(function($rootScope, ngProgressFactory) {
      $rootScope.$on('$stateChangeStart', function() {

        $rootScope.progressbar = ngProgressFactory.createInstance();
        $rootScope.progressbar.setColor("#4684B9");
        $rootScope.progressbar.start();



      })

      $rootScope.$on('$stateChangeSuccess', function() {

        $rootScope.progressbar.complete();

      })
    })


.config(["$locationProvider", function($locationProvider) {
  $locationProvider.html5Mode({ enabled: true, requireBase: false })
}]);
