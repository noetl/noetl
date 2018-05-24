var app = new Vue({
    el: '#app',
    data: {
        city: 'Bucharest',
        model: {
            countryInfo: {
              name: '',
              population: 0,
              area: 0,
              gini: 0,
              capital: '',
              subregion: '',
              flag: '',
              currencies: [{}]
            },
            weatherInfo: {
                weather: [{}],
                main: {
                    temp: ''
                }
            }
        }
    },
    methods: {
        fetchDefault: function () {
            this.city = 'Bucharest'
            this.fetch(this.city)
        },
        fetch: _.debounce(function (city) {
          var vm = this
          axios
            .get('/api/' + city)
            .then(response => {
              vm.model = response.data
            })
            .catch(error => console.log(error))
        }, 500)
    },
    watch: {
        'city': function(newVal, oldVal) {
            this.fetch(newVal)
        }
    },
    mounted: function() {
        this.fetchDefault()
    }
})