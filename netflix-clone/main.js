// Mock Movie Database
const MOVIES = [
  { id: 1, title: 'Inception', year: 2010, rating: 8.8, category: 'trending', image: 'https://via.placeholder.com/200x300?text=Inception', desc: 'A thief who steals corporate secrets through dream-sharing tech.' },
  { id: 2, title: 'The Shawshank Redemption', year: 1994, rating: 9.3, category: 'top-rated', image: 'https://via.placeholder.com/200x300?text=Shawshank', desc: 'Two imprisoned men bond over a number of years, finding solace and eventual redemption.' },
  { id: 3, title: 'The Dark Knight', year: 2008, rating: 9.0, category: 'popular', image: 'https://via.placeholder.com/200x300?text=The+Dark+Knight', desc: 'Batman faces the Joker, a criminal mastermind threatening Gotham.' },
  { id: 4, title: 'Pulp Fiction', year: 1994, rating: 8.9, category: 'top-rated', image: 'https://via.placeholder.com/200x300?text=Pulp+Fiction', desc: 'The lives of two mob hitmen, a boxer, a gangster and his wife intertwine in four tales.' },
  { id: 5, title: 'Fight Club', year: 1999, rating: 8.8, category: 'trending', image: 'https://via.placeholder.com/200x300?text=Fight+Club', desc: 'An insomniac office worker and a soap-maker form an underground fighting club.' },
  { id: 6, title: 'Forrest Gump', year: 1994, rating: 8.8, category: 'popular', image: 'https://via.placeholder.com/200x300?text=Forrest+Gump', desc: 'The presidencies of Kennedy and Johnson unfold through the perspective of an Alabama man.' },
  { id: 7, title: 'The Matrix', year: 1999, rating: 8.7, category: 'trending', image: 'https://via.placeholder.com/200x300?text=The+Matrix', desc: 'A computer hacker learns from rebels about the true nature of his reality.' },
  { id: 8, title: 'Interstellar', year: 2014, rating: 8.6, category: 'popular', image: 'https://via.placeholder.com/200x300?text=Interstellar', desc: 'A team of explorers travel through a wormhole to ensure humanity\'s survival.' },
  { id: 9, title: 'The Godfather', year: 1972, rating: 9.2, category: 'top-rated', image: 'https://via.placeholder.com/200x300?text=The+Godfather', desc: 'The aging patriarch of an organized crime dynasty transfers control of his clandestine empire.' },
  { id: 10, title: 'Gladiator', year: 2000, rating: 8.5, category: 'popular', image: 'https://via.placeholder.com/200x300?text=Gladiator', desc: 'A former Roman General sets out to exact vengeance against the corrupt emperor.' },
  { id: 11, title: 'Avatar', year: 2009, rating: 7.8, category: 'trending', image: 'https://via.placeholder.com/200x300?text=Avatar', desc: 'A paraplegic Marine dispatched to infiltrate an alien world discovers a conflict of interest.' },
  { id: 12, title: 'Oppenheimer', year: 2023, rating: 8.3, category: 'trending', image: 'https://via.placeholder.com/200x300?text=Oppenheimer', desc: 'The story of American scientist J. Robert Oppenheimer and the development of atomic bomb.' },
  { id: 13, title: 'Parasite', year: 2019, rating: 8.6, category: 'top-rated', image: 'https://via.placeholder.com/200x300?text=Parasite', desc: 'Greed and class discrimination threaten the newly formed symbiotic relationship.' },
  { id: 14, title: 'Se7en', year: 1995, rating: 8.6, category: 'popular', image: 'https://via.placeholder.com/200x300?text=Se7en', desc: 'Two detectives hunt a serial killer who uses the seven deadly sins for victims.' },
  { id: 15, title: 'The Silence of the Lambs', year: 1991, rating: 8.6, category: 'top-rated', image: 'https://via.placeholder.com/200x300?text=Silence+of+the+Lambs', desc: 'A young trainee seeks help from an imprisoned cannibal killer to catch another killer.' },
  { id: 16, title: 'Usual Suspects', year: 1995, rating: 8.5, category: 'trending', image: 'https://via.placeholder.com/200x300?text=Usual+Suspects', desc: 'A sole survivor tells of the twisty events leading up to a horrific gun battle.' },
  { id: 17, title: 'The Green Mile', year: 1999, rating: 8.6, category: 'popular', image: 'https://via.placeholder.com/200x300?text=The+Green+Mile', desc: 'The lives of guards on Death Row are affected by an unusual inmate with supernatural powers.' },
  { id: 18, title: 'Saving Private Ryan', year: 1998, rating: 8.6, category: 'trending', image: 'https://via.placeholder.com/200x300?text=Saving+Private+Ryan', desc: 'Following the Normandy Landings, a group of soldiers searches for Private James Ryan.' },
  { id: 19, title: 'The Prestige', year: 2006, rating: 8.5, category: 'top-rated', image: 'https://via.placeholder.com/200x300?text=The+Prestige', desc: 'After a tragic accident, two stage magicians engage in a battle to create the ultimate illusion.' },
  { id: 20, title: 'Goodfellas', year: 1990, rating: 8.7, category: 'popular', image: 'https://via.placeholder.com/200x300?text=Goodfellas', desc: 'The story of Henry Hill and his life in the mob, covering his relationship with his wife Karen Hill.' }
];

let allMovies = [...MOVIES];
let filteredMovies = [...MOVIES];

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
  renderCategories();
  setupSearch();
  setupModal();
  setHeroContent();
});

function setHeroContent() {
  const featured = MOVIES[Math.floor(Math.random() * MOVIES.length)];
  document.getElementById('heroTitle').textContent = featured.title;
  document.getElementById('heroDesc').textContent = featured.desc;
}

function renderCategories() {
  const categories = {
    trending: 'trendingGrid',
    popular: 'popularGrid',
    'top-rated': 'topRatedGrid',
    action: 'actionGrid'
  };

  for (const [category, gridId] of Object.entries(categories)) {
    const movies = MOVIES.filter(m => m.category === category);
    const grid = document.getElementById(gridId);
    grid.innerHTML = movies.map(movie => createMovieCard(movie)).join('');
  }

  attachMovieCardListeners();
}

function createMovieCard(movie) {
  return `
    <div class="movie-card" data-id="${movie.id}">
      <img src="${movie.image}" alt="${movie.title}" onerror="this.src='https://via.placeholder.com/200x300?text=${movie.title}'">
      <div class="movie-info">
        <div class="movie-title">${movie.title}</div>
        <div class="movie-rating">⭐ ${movie.rating}/10</div>
      </div>
    </div>
  `;
}

function attachMovieCardListeners() {
  document.querySelectorAll('.movie-card').forEach(card => {
    card.addEventListener('click', () => {
      const movieId = parseInt(card.dataset.id);
      const movie = MOVIES.find(m => m.id === movieId);
      openModal(movie);
    });
  });
}

function setupSearch() {
  const searchInput = document.getElementById('searchInput');
  searchInput.addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase();
    
    if (query.length === 0) {
      filteredMovies = [...MOVIES];
    } else {
      filteredMovies = MOVIES.filter(movie =>
        movie.title.toLowerCase().includes(query) ||
        movie.desc.toLowerCase().includes(query)
      );
    }

    // Render search results in all grids
    const grids = ['trendingGrid', 'popularGrid', 'topRatedGrid', 'actionGrid'];
    grids.forEach(gridId => {
      const grid = document.getElementById(gridId);
      if (query.length > 0) {
        grid.innerHTML = filteredMovies.map(movie => createMovieCard(movie)).join('');
      } else {
        renderCategories();
      }
    });

    attachMovieCardListeners();
  });
}

function setupModal() {
  const modal = document.getElementById('movieModal');
  const closeBtn = document.querySelector('.close');

  closeBtn.addEventListener('click', closeModal);
  window.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });
}

function openModal(movie) {
  const modal = document.getElementById('movieModal');
  document.getElementById('modalImage').src = movie.image;
  document.getElementById('modalTitle').textContent = movie.title;
  document.getElementById('modalYear').textContent = `Year: ${movie.year}`;
  document.getElementById('modalRating').textContent = `Rating: ⭐ ${movie.rating}/10`;
  document.getElementById('modalDesc').textContent = movie.desc;
  modal.style.display = 'block';
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  const modal = document.getElementById('movieModal');
  modal.style.display = 'none';
  document.body.style.overflow = 'auto';
}
